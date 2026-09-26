"""
Real-time punch listener for ZKTeco devices (live capture).

Keeps a connection open to every enabled Biometric Device that has
"Real-time (Live Capture)" ticked. The device sends each punch the moment
it happens and an Employee Checkin is created immediately.

Works with TCP and UDP devices and does not need the device to reach the
server (the server opens the connection), so it also works when ERPNext
runs in a NAT-ed virtual machine.

Run it as a long-running process under supervisor:

    bench --site <site> execute hr_toolkit.biometric_live.run_listener

The listener checks the device list every 30 seconds, so devices added,
enabled or disabled from the desk are picked up automatically.

On every (re)connect it first imports any punches missed while it was not
connected, then switches to live capture.
"""

import signal
import threading
import time

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from hr_toolkit.biometric_sync import (
    DEVICE_DOCTYPE,
    LOG_DOCTYPE,
    _connect,
    _get_settings,
    _import_attendance,
    _safe_disconnect,
    import_punches,
    update_shift_type_last_sync,
)

DEVICE_REFRESH_SECONDS = 30  # how often the device list is re-read
CAPTURE_TIMEOUT_SECONDS = 10  # socket timeout inside live capture
HEARTBEAT_SECONDS = 60  # how often "Live Last Seen" is written
IDLE_RECONNECT_SECONDS = 30 * 60  # reconnect (with catch-up) after this long without punches
RETRY_DELAY_SECONDS = 30  # wait before reconnecting after an error

_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_listener():
	"""Main loop: start and stop one worker thread per live device."""
	site = frappe.local.site
	sites_path = frappe.local.sites_path

	def _handle_stop(signum, frame):
		_stop_event.set()

	signal.signal(signal.SIGTERM, _handle_stop)
	signal.signal(signal.SIGINT, _handle_stop)

	workers = {}
	_log(f"Biometric live listener started for site {site}")

	while not _stop_event.is_set():
		try:
			frappe.db.rollback()  # fresh read of the device list
			wanted = set(
				frappe.get_all(
					DEVICE_DOCTYPE,
					filters={"enabled": 1, "real_time_capture": 1, "ip_address": ["is", "set"]},
					pluck="name",
				)
			)
		except Exception:
			_log("Could not read device list:\n" + frappe.get_traceback())
			wanted = set(workers)

		# Start workers for new devices
		for device_name in wanted:
			worker = workers.get(device_name)
			if not worker or not worker.thread.is_alive():
				worker = DeviceWorker(site, sites_path, device_name)
				worker.start()
				workers[device_name] = worker

		# Stop workers for removed or disabled devices
		for device_name in list(workers):
			if device_name not in wanted:
				workers[device_name].stop()
				del workers[device_name]

		_stop_event.wait(DEVICE_REFRESH_SECONDS)

	_log("Stopping biometric live listener")
	for worker in workers.values():
		worker.stop()
	for worker in workers.values():
		worker.thread.join(timeout=CAPTURE_TIMEOUT_SECONDS + 5)


def _log(message):
	print(f"[{now_datetime():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


# ---------------------------------------------------------------------------
# One worker per device
# ---------------------------------------------------------------------------


class DeviceWorker:
	def __init__(self, site, sites_path, device_name):
		self.site = site
		self.sites_path = sites_path
		self.device_name = device_name
		self.stop_event = threading.Event()
		self.thread = threading.Thread(target=self._run, name=f"biometric-{device_name}", daemon=True)

	def start(self):
		self.thread.start()

	def stop(self):
		self.stop_event.set()

	def _should_stop(self):
		return self.stop_event.is_set() or _stop_event.is_set()

	def _run(self):
		while not self._should_stop():
			frappe.init(site=self.site, sites_path=self.sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				self._session()
			except Exception as e:
				frappe.db.rollback()
				_log(f"{self.device_name}: {e}")
				self._set_status("Disconnected", f"Live capture error: {e}"[:1000])
				frappe.db.commit()
			finally:
				frappe.destroy()

			if not self._should_stop():
				self.stop_event.wait(RETRY_DELAY_SECONDS)

	def _session(self):
		"""Connect, import missed punches, then capture live until told to stop."""
		device = frappe.get_doc(DEVICE_DOCTYPE, self.device_name)
		conn = None
		try:
			conn = _connect(device)
			self._set_status("Connecting", "Connected. Importing punches missed while offline...")
			frappe.db.commit()

			self._catch_up(device, conn)

			self._set_status("Connected", "Live capture running.")
			frappe.db.set_value(
				DEVICE_DOCTYPE, device.name, "live_connected_since", now_datetime(), update_modified=False
			)
			frappe.db.commit()
			_log(f"{device.name}: live capture started")

			self._capture(device, conn)
		finally:
			if conn:
				try:
					conn.end_live_capture = True
				except Exception:
					pass
			_safe_disconnect(conn)
			if self._should_stop():
				self._set_status("Stopped", "Live capture stopped.")
				frappe.db.commit()

	def _catch_up(self, device, conn):
		conn.disable_device()
		try:
			attendances = conn.get_attendance() or []
		finally:
			conn.enable_device()
		stats = _import_attendance(device, attendances)
		self._after_import(device, stats, "Catch-up")

	def _capture(self, device, conn):
		last_heartbeat = time.monotonic()
		last_punch = time.monotonic()

		for attendance in conn.live_capture(new_timeout=CAPTURE_TIMEOUT_SECONDS):
			now = time.monotonic()

			if attendance is not None:
				last_punch = now
				raw = [(attendance.timestamp, attendance.user_id, getattr(attendance, "punch", None))]
				stats = import_punches(device, raw, use_pointer=False)
				self._after_import(device, stats, "Live")

			if now - last_heartbeat >= HEARTBEAT_SECONDS:
				last_heartbeat = now
				frappe.db.set_value(
					DEVICE_DOCTYPE, device.name, "live_last_seen", now_datetime(), update_modified=False
				)
				frappe.db.commit()
				if self._restart_requested(device.name) or not self._still_wanted(device.name):
					break

			if self._should_stop():
				break

			if now - last_punch >= IDLE_RECONNECT_SECONDS:
				# Reconnect now and then so a silently dropped connection
				# (for example after a device reboot) is recovered.
				break

		conn.end_live_capture = True

	# -- helpers -------------------------------------------------------------

	def _after_import(self, device, stats, source):
		latest = stats.get("latest_punch")
		status = "Partial" if (stats["failed"] or stats["unmatched"]) else "Success"

		values = {"last_synced_on": now_datetime(), "last_sync_status": status}
		if stats["new_punches"] or source == "Catch-up":
			values["last_sync_message"] = (
				f"{source}: {stats['checkins_created']} checkin(s) created"
				+ (f", {stats['duplicates']} already imported" if stats["duplicates"] else "")
				+ (f", {stats['unmatched']} unmatched (User IDs: {stats['unmatched_user_ids']})" if stats["unmatched"] else "")
				+ (f", {stats['failed']} failed" if stats["failed"] else "")
			)[:1000]
		if latest:
			current = frappe.db.get_value(DEVICE_DOCTYPE, device.name, "last_punch_time")
			if not current or latest > get_datetime(current):
				values["last_punch_time"] = latest
		frappe.db.set_value(DEVICE_DOCTYPE, device.name, values, update_modified=False)

		if status != "Success":
			log = frappe.new_doc(LOG_DOCTYPE)
			log.update({k: v for k, v in stats.items() if k != "latest_punch"})
			log.update(
				{
					"device": device.name,
					"triggered_by": "Live",
					"status": status,
					"started_on": now_datetime(),
					"finished_on": now_datetime(),
				}
			)
			log.insert(ignore_permissions=True)

		if stats["checkins_created"] and cint(_get_settings().update_shift_type_last_sync):
			update_shift_type_last_sync(now_datetime())

		frappe.db.commit()

	def _set_status(self, status, message):
		frappe.db.set_value(
			DEVICE_DOCTYPE,
			self.device_name,
			{"live_status": status, "live_last_seen": now_datetime(), "last_sync_message": message},
			update_modified=False,
		)

	def _restart_requested(self, device_name):
		frappe.db.rollback()
		if cint(frappe.db.get_value(DEVICE_DOCTYPE, device_name, "live_restart_requested")):
			frappe.db.set_value(DEVICE_DOCTYPE, device_name, "live_restart_requested", 0, update_modified=False)
			frappe.db.commit()
			return True
		return False

	def _still_wanted(self, device_name):
		row = frappe.db.get_value(DEVICE_DOCTYPE, device_name, ["enabled", "real_time_capture"], as_dict=True)
		return bool(row and cint(row.enabled) and cint(row.real_time_capture))
