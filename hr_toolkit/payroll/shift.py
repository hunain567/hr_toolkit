import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, to_timedelta


def has_time(value):
    """True when a time is set. 00:00:00 (midnight) is a valid time, not empty."""
    return value is not None and value != ""


def _hours(value):
    td = to_timedelta(value) if has_time(value) else None
    return td.total_seconds() / 3600 if td is not None else 0


def hours_between(start, end, allow_zero=False):
    """Hours from start to end. Crossing midnight adds 24 hours (night shift)."""
    if not (has_time(start) and has_time(end)):
        return 0
    hours = _hours(end) - _hours(start)
    if hours < 0 or (hours == 0 and not allow_zero):
        hours += 24
    return hours


def calc_break_minutes(break_start, break_end):
    if not (has_time(break_start) and has_time(break_end)):
        return 0
    return cint(round(hours_between(break_start, break_end, allow_zero=True) * 60))


def calc_shift_hours(start, end, break_minutes):
    if not (has_time(start) and has_time(end)):
        return 0
    return flt(hours_between(start, end) - cint(break_minutes) / 60, 2)


def set_shift_type_hours(doc, method=None):
    """Shift Type validate: calculate Break (Minutes) and Shift Hours."""
    doc.hrt_break_minutes = calc_break_minutes(doc.get("hrt_break_start"), doc.get("hrt_break_end"))
    doc.hrt_shift_hours = calc_shift_hours(doc.start_time, doc.end_time, doc.hrt_break_minutes)
    if flt(doc.hrt_shift_hours) <= 0:
        frappe.throw(_("Shift Hours must be greater than 0. Please check Start Time, End Time and Break."))


def get_shift_types():
    """{shift_type: {hours, multiplier}} for all Shift Types."""
    out = {}
    for r in frappe.get_all(
        "Shift Type",
        fields=[
            "name", "start_time", "end_time", "hrt_break_start", "hrt_break_end",
            "hrt_shift_hours", "hrt_overtime_multiplier",
        ],
    ):
        hours = flt(r.hrt_shift_hours) or calc_shift_hours(
            r.start_time, r.end_time, calc_break_minutes(r.hrt_break_start, r.hrt_break_end)
        )
        out[r.name] = frappe._dict(hours=hours, multiplier=flt(r.hrt_overtime_multiplier))
    return out


def get_shift_assignments(employee, start, end):
    return frappe.db.sql(
        """select shift_type, start_date, end_date from `tabShift Assignment`
           where employee = %s and docstatus = 1 and status = 'Active'
             and start_date <= %s and (end_date is null or end_date >= %s)
           order by start_date desc""",
        (employee, end, start),
        as_dict=True,
    )


def find_assignment(day, assignments):
    for a in assignments:
        if getdate(a.start_date) <= day and (not a.end_date or getdate(a.end_date) >= day):
            return a.shift_type
    return None
