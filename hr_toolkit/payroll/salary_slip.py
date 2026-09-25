import frappe
from frappe.utils import add_days, cint, flt, getdate


def get_settings():
    s = frappe.get_cached_doc("HR Toolkit Settings")
    return frappe._dict(
        working_days=cint(s.working_days) or 26,
        show_fixed_days_on_slip=cint(s.show_fixed_days_on_slip),
        exclude_holidays=cint(s.exclude_holidays),
        count_half_day=cint(s.count_half_day),
        half_day_value=flt(s.half_day_value) or 0.5,
        deduct_before_joining=cint(s.deduct_before_joining),
    )


def get_holidays(employee, start, end):
    try:
        from hrms.hr.utils import get_holiday_dates_for_employee
        return {getdate(d) for d in get_holiday_dates_for_employee(employee, start, end)}
    except Exception:
        return set()


def calculate_deduction_days(doc, method=None):
    """before_validate: fill Full Day Absents and Deduction Days as per HR Toolkit Settings."""
    if not (doc.employee and doc.start_date and doc.end_date):
        return

    s = get_settings()
    start, end = getdate(doc.start_date), getdate(doc.end_date)
    holidays = get_holidays(doc.employee, start, end)

    rows = frappe.get_all(
        "Attendance",
        filters={
            "employee": doc.employee,
            "docstatus": 1,
            "status": ["in", ["Absent", "Half Day"]],
            "attendance_date": ["between", [start, end]],
        },
        fields=["attendance_date", "status"],
    )

    full, half = 0, 0
    for r in rows:
        if s.exclude_holidays and getdate(r.attendance_date) in holidays:
            continue
        if r.status == "Absent":
            full += 1
        else:
            half += 1

    outside = 0
    if s.deduct_before_joining:
        joining, relieving = frappe.db.get_value(
            "Employee", doc.employee, ["date_of_joining", "relieving_date"]
        )
        joining = getdate(joining) if joining else None
        relieving = getdate(relieving) if relieving else None
        d = start
        while d <= end:
            if d not in holidays and ((joining and d < joining) or (relieving and d > relieving)):
                outside += 1
            d = getdate(add_days(d, 1))

    deduct = full + outside + (half * s.half_day_value if s.count_half_day else 0)

    doc.full_absent_days = full
    doc.fixed_working_days = s.working_days
    doc.deduct_days = min(deduct, s.working_days)


def set_fixed_payment_days(doc, method=None):
    """validate: after the standard calculation, set Working Days and Payment Days from settings."""
    s = get_settings()
    if not s.show_fixed_days_on_slip:
        return
    doc.total_working_days = s.working_days
    doc.payment_days = s.working_days - flt(doc.deduct_days)
