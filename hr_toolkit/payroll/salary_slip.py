import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate


def get_settings():
    s = frappe.get_cached_doc("HR Toolkit Settings")
    return frappe._dict(
        working_days=cint(s.working_days) or 26,
        show_fixed_days_on_slip=cint(s.show_fixed_days_on_slip),
        count_unmarked_as_absent=cint(s.count_unmarked_as_absent),
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


def get_monthly_salary(employee, salary_structure, end_date):
    """Base salary from the latest submitted Salary Structure Assignment on or before end_date."""
    filters = {"employee": employee, "docstatus": 1, "from_date": ["<=", end_date]}
    if salary_structure:
        filters["salary_structure"] = salary_structure
    base = frappe.db.get_value(
        "Salary Structure Assignment", filters, "base", order_by="from_date desc"
    )
    return flt(base)


def calculate_deduction_days(doc, method=None):
    """before_validate: fill monthly salary and absent/unmarked/deduction days as per HR Toolkit Settings."""
    if not (doc.employee and doc.start_date and doc.end_date):
        return

    doc.hrt_monthly_salary = get_monthly_salary(doc.employee, doc.salary_structure, doc.end_date)

    s = get_settings()
    start, end = getdate(doc.start_date), getdate(doc.end_date)
    today = getdate(nowdate())
    holidays = get_holidays(doc.employee, start, end)

    joining, relieving = frappe.db.get_value(
        "Employee", doc.employee, ["date_of_joining", "relieving_date"]
    )
    joining = getdate(joining) if joining else None
    relieving = getdate(relieving) if relieving else None

    attendance = {
        getdate(r.attendance_date): r.status
        for r in frappe.get_all(
            "Attendance",
            filters={
                "employee": doc.employee,
                "docstatus": 1,
                "attendance_date": ["between", [start, end]],
            },
            fields=["attendance_date", "status"],
        )
    }

    # Marked Absent / Half Day
    full, half = 0, 0
    for day, status in attendance.items():
        if s.exclude_holidays and day in holidays:
            continue
        if status == "Absent":
            full += 1
        elif status == "Half Day":
            half += 1

    # Unmarked working days and days outside employment
    unmarked, outside = 0, 0
    d = start
    while d <= end:
        if d not in holidays:
            in_service = not ((joining and d < joining) or (relieving and d > relieving))
            if not in_service:
                if s.deduct_before_joining:
                    outside += 1
            elif s.count_unmarked_as_absent and d <= today and d not in attendance:
                unmarked += 1
        d = getdate(add_days(d, 1))

    deduct = full + unmarked + outside + (half * s.half_day_value if s.count_half_day else 0)

    doc.full_absent_days = full
    doc.hrt_unmarked_days = unmarked
    doc.fixed_working_days = s.working_days
    doc.deduct_days = min(deduct, s.working_days)


def set_fixed_payment_days(doc, method=None):
    """validate: after the standard calculation, set Working, Absent and Payment Days from settings."""
    s = get_settings()
    if not s.show_fixed_days_on_slip:
        return
    doc.total_working_days = s.working_days
    doc.absent_days = flt(doc.full_absent_days) + flt(doc.hrt_unmarked_days)
    doc.payment_days = s.working_days - flt(doc.deduct_days)
