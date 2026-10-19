from datetime import timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, to_timedelta

from hr_toolkit.payroll.shift import (
    calc_break_minutes,
    has_time,
    calc_shift_hours,
    find_assignment,
    get_shift_assignments,
)

WORKING_STATUSES = ("Present", "Half Day", "Work From Home")


def get_overtime_settings():
    s = frappe.get_cached_doc("HR Toolkit Settings")
    return frappe._dict(
        enabled=cint(s.get("enable_overtime")),
        from_checkin=cint(s.get("overtime_from_checkin")),
        min_minutes=cint(s.get("overtime_min_minutes")),
        rounding=cint(s.get("overtime_rounding")),
        round_minutes=cint(s.get("overtime_round_minutes")),
    )


def get_employee_shift(employee, day, attendance_shift=None):
    if attendance_shift:
        return attendance_shift
    assignment = find_assignment(day, get_shift_assignments(employee, day, day))
    return assignment or frappe.db.get_value("Employee", employee, "default_shift")


def apply_overtime_rules(ot_minutes, s):
    """Minimum and rounding as per HR Toolkit Settings. Returns minutes."""
    ot_minutes = max(0, ot_minutes)
    if s.min_minutes and ot_minutes < s.min_minutes:
        return 0
    if s.rounding and s.round_minutes:
        return (int(ot_minutes) // s.round_minutes) * s.round_minutes
    return ot_minutes


def compute_overtime(employee, day, shift, settings=None):
    """Overtime for one employee on one day from Employee Checkin.
    Returns {in_time, out_time, working_hours, overtime_hours} or None when not enough checkins."""
    s = settings or get_overtime_settings()
    day = getdate(day)
    if not shift:
        return None

    st = frappe.db.get_value(
        "Shift Type",
        shift,
        ["start_time", "end_time", "hrt_break_start", "hrt_break_end", "hrt_shift_hours",
         "begin_check_in_before_shift_start_time"],
        as_dict=True,
    )
    if not st or not has_time(st.start_time) or not has_time(st.end_time):
        return None

    base = get_datetime(day)
    shift_start = base + to_timedelta(st.start_time)

    # 24 hour window starting before the shift, so night shift checkouts after midnight belong to this day
    window_start = shift_start - timedelta(minutes=cint(st.begin_check_in_before_shift_start_time) or 60)
    window_end = window_start + timedelta(hours=24) - timedelta(seconds=1)
    logs = frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "time": ["between", [window_start, window_end]]},
        pluck="time",
        order_by="time asc",
    )
    if len(logs) < 2:
        return None

    first, last = get_datetime(logs[0]), get_datetime(logs[-1])
    worked = (last - first).total_seconds() / 3600

    # Deduct the break only when the employee was in for the whole break
    break_minutes = calc_break_minutes(st.hrt_break_start, st.hrt_break_end)
    deducted_break = 0
    if break_minutes:
        break_start = base + to_timedelta(st.hrt_break_start)
        if break_start < shift_start:
            break_start += timedelta(days=1)  # break after midnight in a night shift
        break_end = break_start + timedelta(minutes=break_minutes)
        if first <= break_start and last >= break_end:
            deducted_break = break_minutes

    net_hours = worked - deducted_break / 60
    shift_hours = flt(st.hrt_shift_hours) or calc_shift_hours(st.start_time, st.end_time, break_minutes)
    ot_minutes = apply_overtime_rules((net_hours - shift_hours) * 60, s)

    return frappe._dict(
        in_time=first,
        out_time=last,
        working_hours=flt(net_hours, 2),
        overtime_hours=flt(ot_minutes / 60, 2),
    )


def set_overtime_from_checkins(doc, method=None):
    """Attendance validate: In Time, Out Time, Working Hours and Overtime Hours (information only).
    Salary uses submitted Overtime Entry."""
    s = get_overtime_settings()
    if not (s.enabled and s.from_checkin) or doc.status not in WORKING_STATUSES:
        return
    day = getdate(doc.attendance_date)
    result = compute_overtime(doc.employee, day, get_employee_shift(doc.employee, day, doc.shift), s)
    if not result:
        return
    doc.in_time = result.in_time
    doc.out_time = result.out_time
    doc.working_hours = result.working_hours
    doc.overtime_hours = result.overtime_hours
