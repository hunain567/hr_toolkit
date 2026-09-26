"""
Biometric attendance sync for ZKTeco devices.

Pulls punches from every enabled "Biometric Device" over the network
(using the pyzk library) and creates "Employee Checkin" records.
Employees are matched on the standard Employee field
"Attendance Device ID (Biometric/RF tag ID)" (attendance_device_id).

Entry points:
    scheduled_sync()        - called by the scheduler every 5 minutes
    cleanup_sync_logs()     - called daily, deletes old sync logs
    sync_now(device_name)   - "Sync Now" button (whitelisted)
    sync_all_now()          - "Sync All Devices Now" button (whitelisted)
    test_connection(...)    - "Test Connection" button (whitelisted)
    reset_sync_pointer(...) - "Reset Sync Pointer" button (whitelisted)
    sync_device_clock(...)  - "Set Device Clock" button (whitelisted)
"""

import frappe
from frappe import _
from frappe.utils import (
    add_days,
    add_to_date,
    cint,
    get_datetime,
    getdate,
    now_datetime,
    time_diff_in_seconds,
)

DEVICE_DOCTYPE = "Biometric Device"
LOG_DOCTYPE = "Biometric Sync Log"
SETTINGS_DOCTYPE = "Biometric Settings"
PULL_MODE = "Pull (TCP/IP)"
PUSH_MODE = "Push (ADMS)"
ALLOWED_ROLES = ("System Manager", "HR Manager")

# ZKTeco punch state codes
IN_PUNCH_CODES = {0, 3, 4}  # Check-In, Break-In, Overtime-In
OUT_PUNCH_CODES = {1, 2, 5}  # Check-Out, Break-Out, Overtime-Out

COMMIT_EVERY = 200
MIN_INTERVAL_MINUTES = 5
FUTURE_TOLERANCE_MINUTES = 60
TEST_CONNECTION_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Device connection helpers
# ---------------------------------------------------------------------------


def _get_zk_class():
    try:
        from zk import ZK
    except ImportError:
        frappe.throw(
            _(
                "The Python package 'pyzk' is not installed. "
                "Run this from the bench folder: ./env/bin/pip install pyzk"
            )
        )
    return ZK


def _connect(device, timeout=None):
    """Open a connection to the device and return the pyzk connection object."""
    ZK = _get_zk_class()
    zk = ZK(
        device.ip_address,
        port=cint(device.port) or 4370,
        timeout=cint(timeout or device.timeout) or 30,
        password=cint(device.comm_password),
        force_udp=bool(cint(device.force_udp)),
        ommit_ping=True,
    )
    return zk.connect()


def _safe_disconnect(conn):
    if not conn:
        return
    try:
        conn.enable_device()
    except Exception:
        pass
    try:
        conn.disconnect()
    except Exception:
        pass


def _check_permission(device_name=None):
    if device_name:
        frappe.has_permission(DEVICE_DOCTYPE, "write", device_name, throw=True)
    else:
        frappe.only_for(ALLOWED_ROLES)


def _get_settings():
    return frappe.get_cached_doc(SETTINGS_DOCTYPE)


# ---------------------------------------------------------------------------
# Whitelisted actions (called from the device / settings form)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def test_connection(device_name):
    """Connect to the device, read basic info and store it on the device record."""
    _check_permission(device_name)
    device = frappe.get_doc(DEVICE_DOCTYPE, device_name)

    conn = None
    try:
        conn = _connect(device, timeout=min(cint(device.timeout) or 30, TEST_CONNECTION_TIMEOUT))
        conn.read_sizes()
        info = {
            "serial_number": _safe_call(conn.get_serialnumber),
            "firmware_version": _safe_call(conn.get_firmware_version),
            "platform": _safe_call(conn.get_platform),
            "device_model_name": _safe_call(conn.get_device_name),
            "user_count": cint(getattr(conn, "users", 0)),
            "record_count": cint(getattr(conn, "records", 0)),
            "device_time": _safe_call(conn.get_time),
            "info_checked_on": now_datetime(),
        }
    except Exception as e:
        frappe.throw(
            _("Could not connect to {0} ({1}:{2}).<br><br>Error: {3}").format(
                device.name, device.ip_address, device.port, frappe.bold(str(e))
            ),
            title=_("Connection Failed"),
        )
    finally:
        _safe_disconnect(conn)

    frappe.db.set_value(DEVICE_DOCTYPE, device.name, info, update_modified=False)

    server_time = now_datetime()
    info["server_time"] = server_time
    info["clock_difference_seconds"] = (
        int(time_diff_in_seconds(info["device_time"], server_time)) if info["device_time"] else None
    )
    return info


@frappe.whitelist()
def sync_now(device_name):
    """Queue a background sync for one device."""
    _check_permission(device_name)
    enabled, ip_address = frappe.db.get_value(DEVICE_DOCTYPE, device_name, ["enabled", "ip_address"])
    if not enabled:
        frappe.throw(_("Device {0} is disabled.").format(device_name))
    if not ip_address:
        frappe.throw(_("Set the IP Address on {0} to pull punches from it.").format(device_name))
    if cint(frappe.db.get_value(DEVICE_DOCTYPE, device_name, "real_time_capture")):
        # The live listener holds the connection; ask it to reconnect and catch up.
        frappe.db.set_value(DEVICE_DOCTYPE, device_name, "live_restart_requested", 1, update_modified=False)
        return "live"
    enqueue_sync(device_name, "Manual")
    return True


@frappe.whitelist()
def sync_all_now():
    """Queue a background sync for every enabled device."""
    _check_permission()
    devices = frappe.get_all(
        DEVICE_DOCTYPE,
        filters={"enabled": 1, "ip_address": ["is", "set"], "real_time_capture": 0},
        pluck="name",
    )
    for device_name in frappe.get_all(
        DEVICE_DOCTYPE, filters={"enabled": 1, "real_time_capture": 1}, pluck="name"
    ):
        frappe.db.set_value(DEVICE_DOCTYPE, device_name, "live_restart_requested", 1, update_modified=False)
    for device_name in devices:
        enqueue_sync(device_name, "Manual")
    return len(devices)


@frappe.whitelist()
def reset_sync_pointer(device_name):
    """
    Clear the "Last Imported Punch" so the next sync re-reads every punch
    (from "Import Punches From" onward). Already imported punches are
    skipped as duplicates, so this is safe to run.
    """
    _check_permission(device_name)
    frappe.db.set_value(DEVICE_DOCTYPE, device_name, "last_punch_time", None, update_modified=False)
    return True


@frappe.whitelist()
def sync_device_clock(device_name):
    """Set the device clock to the current server time."""
    _check_permission(device_name)
    device = frappe.get_doc(DEVICE_DOCTYPE, device_name)

    conn = None
    try:
        conn = _connect(device, timeout=min(cint(device.timeout) or 30, TEST_CONNECTION_TIMEOUT))
        server_time = now_datetime()
        conn.set_time(server_time)
    except Exception as e:
        frappe.throw(
            _("Could not set the clock on {0}.<br><br>Error: {1}").format(device.name, frappe.bold(str(e))),
            title=_("Clock Update Failed"),
        )
    finally:
        _safe_disconnect(conn)

    frappe.db.set_value(
        DEVICE_DOCTYPE,
        device.name,
        {"device_time": server_time, "info_checked_on": server_time},
        update_modified=False,
    )
    return server_time


def _safe_call(fn):
    try:
        return fn()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def scheduled_sync():
    """Runs every 5 minutes. Queues devices whose sync interval has passed."""
    settings = _get_settings()
    if not cint(settings.enable_auto_sync):
        return

    interval_seconds = max(cint(settings.sync_interval_minutes) or 15, MIN_INTERVAL_MINUTES) * 60
    now = now_datetime()

    devices = frappe.get_all(
        DEVICE_DOCTYPE,
        filters={"enabled": 1, "connection_mode": PULL_MODE, "real_time_capture": 0},
        fields=["name", "last_synced_on"],
    )
    for device in devices:
        # 30 second grace so a 15 minute interval is not pushed to 20 minutes
        # by small scheduler delays.
        if device.last_synced_on and time_diff_in_seconds(now, device.last_synced_on) < interval_seconds - 30:
            continue
        enqueue_sync(device.name, "Scheduler")


def cleanup_sync_logs():
    """Runs daily. Deletes sync logs older than the configured retention."""
    days = cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, "keep_logs_for_days")) or 30
    frappe.db.delete(LOG_DOCTYPE, {"creation": ["<", add_days(now_datetime(), -days)]})
    frappe.db.commit()


def enqueue_sync(device_name, triggered_by):
    frappe.enqueue(
        "hr_toolkit.biometric_sync.sync_device",
        queue="long",
        timeout=1800,
        job_id=f"biometric_sync::{frappe.local.site}::{device_name}",
        deduplicate=True,
        device_name=device_name,
        triggered_by=triggered_by,
    )


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------


def sync_device(device_name, triggered_by="Manual"):
    """Pull punches from one device and create Employee Checkins."""
    device = frappe.get_doc(DEVICE_DOCTYPE, device_name)
    settings = _get_settings()

    log = frappe.new_doc(LOG_DOCTYPE)
    log.device = device.name
    log.triggered_by = triggered_by
    log.started_on = now_datetime()

    stats = {}
    conn = None
    try:
        conn = _connect(device)
        conn.disable_device()  # lock the keypad while reading
        try:
            attendances = conn.get_attendance() or []
        finally:
            try:
                conn.enable_device()
            except Exception:
                pass

        stats = _import_attendance(device, attendances)
        log.update({k: v for k, v in stats.items() if k != "latest_punch"})

        if stats["failed"] or stats["unmatched"]:
            log.status = "Partial"
        else:
            log.status = "Success"

    except Exception as e:
        frappe.db.rollback()
        log.status = "Failed"
        log.error_message = str(e)[:1000]
        log.error_log = frappe.get_traceback()
    finally:
        _safe_disconnect(conn)
        frappe.clear_messages()

    log.finished_on = now_datetime()

    skip_log = (
        triggered_by == "Scheduler"
        and log.status == "Success"
        and not cint(log.checkins_created)
        and not cint(settings.log_empty_syncs)
    )
    if not skip_log:
        log.insert(ignore_permissions=True)

    _update_device_status(device, log, stats.get("latest_punch"))

    if log.status != "Failed" and cint(log.checkins_created) and cint(settings.update_shift_type_last_sync):
        _update_shift_type_last_sync(log.finished_on)

    frappe.db.commit()
    return log.name if not skip_log else None


def _import_attendance(device, attendances):
    """Convert pyzk Attendance objects and import them (pull mode)."""
    raw = [
        (att.timestamp, att.user_id, getattr(att, "punch", None))
        for att in attendances
        if getattr(att, "timestamp", None)
    ]
    return import_punches(device, raw, use_pointer=True, total_fetched=len(attendances))


def import_punches(device, raw_punches, use_pointer=True, total_fetched=None):
    """
    Create Employee Checkins from raw punches.

    raw_punches: list of (timestamp, device_user_id, punch_state_code)
    use_pointer: pull mode only imports punches after "Last Imported Punch".
                 Push mode sends each punch once, so only "Import Punches From"
                 is applied and duplicates are skipped.
    """
    stats = {
        "total_fetched": len(raw_punches) if total_fetched is None else total_fetched,
        "new_punches": 0,
        "checkins_created": 0,
        "duplicates": 0,
        "unmatched": 0,
        "failed": 0,
        "skipped_future": 0,
        "unmatched_user_ids": "",
        "error_message": "",
        "latest_punch": None,
    }

    # Only punches after the last imported one (or after "Import Punches From")
    if use_pointer and device.last_punch_time:
        cutoff = get_datetime(device.last_punch_time)
        is_new = lambda ts: ts > cutoff  # noqa: E731
    elif device.import_from_date:
        cutoff = get_datetime(getdate(device.import_from_date))
        is_new = lambda ts: ts >= cutoff  # noqa: E731
    else:
        is_new = lambda ts: True  # noqa: E731

    future_limit = add_to_date(now_datetime(), minutes=FUTURE_TOLERANCE_MINUTES)

    punches = []
    for timestamp, user_id, punch_code in raw_punches:
        ts = get_datetime(timestamp)
        if not is_new(ts):
            continue
        if ts > future_limit:
            # A wrong device clock must not push the sync pointer into the future.
            stats["skipped_future"] += 1
            continue
        punches.append((ts, str(user_id).strip(), punch_code))

    stats["new_punches"] = len(punches)
    if not punches:
        return stats

    punches.sort(key=lambda p: p[0])
    stats["latest_punch"] = punches[-1][0]

    # Map device user IDs to employees in one query
    device_user_ids = list({p[1] for p in punches})
    employee_map = {
        row.attendance_device_id: row.name
        for row in frappe.get_all(
            "Employee",
            filters={"attendance_device_id": ["in", device_user_ids], "status": ["!=", "Left"]},
            fields=["name", "attendance_device_id"],
        )
    }

    # Existing checkins in the same period, for duplicate detection
    existing = set()
    if employee_map:
        rows = frappe.get_all(
            "Employee Checkin",
            filters={
                "employee": ["in", list(set(employee_map.values()))],
                "time": [">=", punches[0][0]],
            },
            fields=["employee", "time"],
        )
        existing = {(r.employee, get_datetime(r.time)) for r in rows}

    unmatched_ids = set()
    errors = []

    for index, (ts, user_id, punch_code) in enumerate(punches, start=1):
        employee = employee_map.get(user_id)
        if not employee:
            stats["unmatched"] += 1
            unmatched_ids.add(user_id)
            continue

        key = (employee, ts)
        if key in existing:
            stats["duplicates"] += 1
            continue

        frappe.db.savepoint("biometric_checkin")
        try:
            checkin = frappe.new_doc("Employee Checkin")
            checkin.employee = employee
            checkin.time = ts
            checkin.device_id = device.name
            log_type = _resolve_log_type(device.punch_direction, punch_code)
            if log_type:
                checkin.log_type = log_type
            checkin.insert(ignore_permissions=True)
            existing.add(key)
            stats["checkins_created"] += 1
        except Exception as e:
            frappe.db.rollback(save_point="biometric_checkin")
            stats["failed"] += 1
            if len(errors) < 50:
                errors.append(f"{user_id} / {employee} @ {ts}: {e}")
        finally:
            frappe.clear_messages()

        if index % COMMIT_EVERY == 0:
            frappe.db.commit()

    stats["unmatched_user_ids"] = ", ".join(sorted(unmatched_ids, key=_natural_key))
    stats["error_message"] = "\n".join(errors)
    return stats


def _resolve_log_type(direction, punch_code):
    if direction == "IN":
        return "IN"
    if direction == "OUT":
        return "OUT"
    if direction == "Device Punch State" and punch_code is not None:
        code = cint(punch_code)
        if code in IN_PUNCH_CODES:
            return "IN"
        if code in OUT_PUNCH_CODES:
            return "OUT"
    # AUTO: leave log_type empty (Shift Type / existing server scripts decide)
    return None


def update_shift_type_last_sync(sync_time):
    _update_shift_type_last_sync(sync_time)


def update_device_status(device, log, latest_punch):
    _update_device_status(device, log, latest_punch)


def _update_device_status(device, log, latest_punch):
    values = {
        "last_synced_on": log.finished_on,
        "last_sync_status": log.status,
        "last_sync_message": _status_message(log),
    }
    if latest_punch and log.status != "Failed":
        current = get_datetime(device.last_punch_time) if device.last_punch_time else None
        if not current or latest_punch > current:
            values["last_punch_time"] = latest_punch
    frappe.db.set_value(DEVICE_DOCTYPE, device.name, values, update_modified=False)


def _status_message(log):
    if log.status == "Failed":
        return _("Sync failed: {0}").format(log.error_message or "")[:1000]
    parts = [
        _("{0} new punch(es), {1} checkin(s) created").format(
            cint(log.new_punches), cint(log.checkins_created)
        )
    ]
    if cint(log.duplicates):
        parts.append(_("{0} already imported").format(cint(log.duplicates)))
    if cint(log.unmatched):
        parts.append(_("{0} unmatched (User IDs: {1})").format(cint(log.unmatched), log.unmatched_user_ids))
    if cint(log.failed):
        parts.append(_("{0} failed").format(cint(log.failed)))
    if cint(log.skipped_future):
        parts.append(_("{0} future-dated skipped, check device clock").format(cint(log.skipped_future)))
    return "; ".join(parts)[:1000]


def _update_shift_type_last_sync(sync_time):
    """Let Shift Type Auto Attendance process the newly imported checkins."""
    if not frappe.db.has_column("Shift Type", "last_sync_of_checkin"):
        return
    for shift_type in frappe.get_all("Shift Type", filters={"enable_auto_attendance": 1}, pluck="name"):
        frappe.db.set_value("Shift Type", shift_type, "last_sync_of_checkin", sync_time, update_modified=False)


def _natural_key(value):
    return (0, int(value), "") if value.isdigit() else (1, 0, value)
