from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, get_datetime, getdate, to_timedelta

from hr_toolkit.payroll.attendance import set_overtime_from_checkins
from hr_toolkit.payroll.shift import has_time
from hr_toolkit.payroll.salary_slip import get_off_days, get_settings

ROLES = ["System Manager", "HR Manager", "HR User"]
MANUAL_DEVICE = "Manual"
MAX_DAYS = 62


class CheckinAdjustmentTool(Document):
    pass


def _time_str(value):
    td = to_timedelta(value) if has_time(value) else None
    return (datetime.min + td).strftime("%H:%M") if td is not None else None


def _day_window(day, st):
    """Shift start, shift end and the 24 hour checkin window for the day (whole day when no shift)."""
    base = get_datetime(day)
    if not st or not has_time(st.start_time) or not has_time(st.end_time):
        return None, None, base, base + timedelta(hours=24) - timedelta(seconds=1)
    start = base + to_timedelta(st.start_time)
    end = base + to_timedelta(st.end_time)
    if end <= start:
        end += timedelta(days=1)
    window_start = start - timedelta(minutes=cint(st.begin_check_in_before_shift_start_time) or 60)
    return start, end, window_start, window_start + timedelta(hours=24) - timedelta(seconds=1)


@frappe.whitelist()
def get_month_checkins(employee, from_date, to_date):
    """One row per day with the first checkin as In and the last checkin as Out."""
    frappe.only_for(ROLES)
    start_date, end_date = getdate(from_date), getdate(to_date)
    if end_date < start_date:
        frappe.throw(_("To Date cannot be before From Date."))
    if date_diff(end_date, start_date) + 1 > MAX_DAYS:
        frappe.throw(_("Please select a period of {0} days or less.").format(MAX_DAYS))

    emp = frappe.db.get_value(
        "Employee", employee, ["default_shift", "date_of_joining", "relieving_date"], as_dict=True
    )
    joining = getdate(emp.date_of_joining) if emp.date_of_joining else None
    relieving = getdate(emp.relieving_date) if emp.relieving_date else None

    assignments = frappe.db.sql(
        """select shift_type, start_date, end_date from `tabShift Assignment`
           where employee = %s and docstatus = 1 and status = 'Active'
             and start_date <= %s and (end_date is null or end_date >= %s)""",
        (employee, end_date, start_date), as_dict=True,
    )
    attendance = {
        getdate(r.attendance_date): r
        for r in frappe.get_all(
            "Attendance",
            filters={"employee": employee, "docstatus": 1, "attendance_date": ["between", [start_date, end_date]]},
            fields=["attendance_date", "status", "shift", "working_hours", "overtime_hours"],
        )
    }
    shift_types = {
        s.name: s
        for s in frappe.get_all(
            "Shift Type", fields=["name", "start_time", "end_time", "begin_check_in_before_shift_start_time"]
        )
    }
    logs = frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "time": ["between", [add_days(start_date, -1), add_days(end_date, 2)]]},
        fields=["name", "time", "log_type"],
        order_by="time asc",
    )
    weekly, holidays = get_off_days(employee, start_date, end_date, get_settings().weekly_off_day)

    rows = []
    day = start_date
    while day <= end_date:
        att = attendance.get(day)
        shift = (att.shift if att else None)
        if not shift:
            for a in assignments:
                if getdate(a.start_date) <= day and (not a.end_date or getdate(a.end_date) >= day):
                    shift = a.shift_type
                    break
        shift = shift or emp.default_shift
        st = shift_types.get(shift)
        shift_start, shift_end, window_start, window_end = _day_window(day, st)
        day_logs = [l for l in logs if window_start <= get_datetime(l.time) <= window_end]

        in_log = out_log = None
        if len(day_logs) >= 2:
            in_log, out_log = day_logs[0], day_logs[-1]
        elif len(day_logs) == 1:
            log = day_logs[0]
            t = get_datetime(log.time)
            is_out = log.log_type == "OUT" or (
                log.log_type != "IN" and shift_start and abs(t - shift_end) < abs(t - shift_start)
            )
            if is_out:
                out_log = log
            else:
                in_log = log

        remarks = []
        if (joining and day < joining) or (relieving and day > relieving):
            remarks.append("Not in service")
        elif att and att.status == "On Leave":
            remarks.append("On Leave")
        elif day in weekly:
            remarks.append("Weekly Off")
        elif day in holidays:
            remarks.append("Holiday")
        if not shift:
            remarks.append("No Shift")
        if not day_logs:
            remarks.append("No Checkin")
        elif not in_log:
            remarks.append("Missing IN")
        elif not out_log:
            remarks.append("Missing OUT")

        in_time = _time_str(get_datetime(in_log.time).strftime("%H:%M:%S")) if in_log else None
        out_time = _time_str(get_datetime(out_log.time).strftime("%H:%M:%S")) if out_log else None
        rows.append({
            "date": day,
            "day": day.strftime("%a"),
            "shift": shift,
            "status": att.status if att else "",
            "in_time": in_time,
            "out_time": out_time,
            "working_hours": att.working_hours if att else 0,
            "overtime_hours": att.overtime_hours if att else 0,
            "remarks": ", ".join(remarks),
            "in_checkin": in_log.name if in_log else "",
            "out_checkin": out_log.name if out_log else "",
            "original_in": in_time or "",
            "original_out": out_time or "",
        })
        day = getdate(add_days(day, 1))
    return rows


def _update_attendance(employee, day, shift):
    att = frappe.db.get_value(
        "Attendance", {"employee": employee, "attendance_date": day, "docstatus": 1},
        ["name", "status"], as_dict=True,
    )
    if att and att.status == "On Leave":
        return False
    if att and att.status in ("Present", "Half Day", "Work From Home"):
        doc = frappe.get_doc("Attendance", att.name)
        set_overtime_from_checkins(doc)
        if doc.in_time:
            doc.db_set({
                "in_time": doc.in_time, "out_time": doc.out_time,
                "working_hours": doc.working_hours, "overtime_hours": doc.overtime_hours,
            }, update_modified=False)
        return True
    if att:  # Absent -> cancel and mark Present
        frappe.get_doc("Attendance", att.name).cancel()

    doc = frappe.get_doc({
        "doctype": "Attendance",
        "employee": employee,
        "company": frappe.db.get_value("Employee", employee, "company"),
        "attendance_date": day,
        "status": "Present",
        "shift": shift,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return True


def _apply(employee, checkin, new_dt, log_type, counts):
    """Create, update or delete one checkin."""
    if checkin and not new_dt:
        frappe.delete_doc("Employee Checkin", checkin, ignore_permissions=True)
        counts["deleted"] += 1
    elif checkin and new_dt:
        doc = frappe.get_doc("Employee Checkin", checkin)
        if get_datetime(doc.time) != new_dt:
            doc.time = new_dt
            doc.log_type = log_type
            doc.flags.ignore_permissions = True
            doc.save()
            counts["updated"] += 1
    elif new_dt:
        frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee,
            "time": new_dt,
            "log_type": log_type,
            "device_id": MANUAL_DEVICE,
        }).insert(ignore_permissions=True)
        counts["created"] += 1


@frappe.whitelist()
def save_month_checkins(employee, rows, mark_attendance=1):
    """Save only the changed days: create, update or delete checkins and update attendance."""
    frappe.only_for(ROLES)
    rows = frappe.parse_json(rows) or []
    counts = {"created": 0, "updated": 0, "deleted": 0, "attendance": 0}
    errors = []

    for row in rows:
        row = frappe._dict(row)
        if (row.in_time or "") == (row.original_in or "") and (row.out_time or "") == (row.original_out or ""):
            continue

        day = getdate(row.date)
        frappe.db.savepoint("hrt_checkin_day")
        try:
            base = get_datetime(day)
            st = frappe.db.get_value("Shift Type", row.shift, ["start_time"], as_dict=True) if row.shift else None
            in_dt = base + _parse_hm(row.in_time) if row.in_time else None
            out_dt = None
            if row.out_time:
                out_dt = base + _parse_hm(row.out_time)
                reference = in_dt or (base + to_timedelta(st.start_time) if st and has_time(st.start_time) else None)
                if reference and out_dt <= reference:
                    out_dt += timedelta(days=1)  # night shift checkout after midnight

            _apply(employee, row.in_checkin, in_dt, "IN", counts)
            _apply(employee, row.out_checkin, out_dt, "OUT", counts)

            if cint(mark_attendance) and (in_dt or out_dt) and _update_attendance(employee, day, row.shift):
                counts["attendance"] += 1
        except Exception as e:
            frappe.db.rollback(save_point="hrt_checkin_day")
            frappe.clear_messages()
            errors.append(f"{day}: {e}")

    counts["errors"] = errors
    return counts


def _parse_hm(value):
    """Accept 8, 830, 0830, 08:30, 8.30 or 08:30:00 and return a timedelta."""
    text = str(value).strip().replace(".", ":")
    if text.isdigit():
        text = f"{text}:00" if len(text) <= 2 else f"{text[:-2]}:{text[-2:]}"
    parts = text.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        frappe.throw(_("Invalid time {0}. Use HH:MM, for example 08:30.").format(value))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        frappe.throw(_("Invalid time {0}. Use HH:MM, for example 08:30.").format(value))
    return timedelta(hours=hours, minutes=minutes)
