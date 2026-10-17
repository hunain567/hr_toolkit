import frappe
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

FIXED_DIVISORS = {"26-Day Basis": 26, "30-Day Basis": 30}


def get_settings():
    s = frappe.get_cached_doc("HR Toolkit Settings")
    return frappe._dict(
        method=s.get("calculation_method") or "26-Day Basis",
        precision=cint(s.get("rounding_precision")),
        show_on_slip=cint(s.get("show_fixed_days_on_slip")),
        weekly_off_day=s.get("weekly_off_day") or "",
        weekly_off_paid=cint(s.get("weekly_off_paid")),
        sandwich_rule=cint(s.get("sandwich_rule")),
        holidays_paid=cint(s.get("holidays_paid")),
        exclude_holidays=cint(s.get("exclude_holidays")),
        count_unmarked=cint(s.get("count_unmarked_as_absent")),
        cutoff=s.get("attendance_cutoff") or "Today",
        deduct_lwp=cint(s.get("deduct_lwp")),
        count_half_day=cint(s.get("count_half_day")),
        half_day_value=flt(s.get("half_day_value")) or 0.5,
        proration_basis=s.get("proration_basis") or "Working Days",
    )


def get_base_salary(employee, salary_structure, end_date):
    """Base salary from the latest submitted Salary Structure Assignment on or before end_date."""
    filters = {"employee": employee, "docstatus": 1, "from_date": ["<=", end_date]}
    if salary_structure:
        filters["salary_structure"] = salary_structure
    return flt(
        frappe.db.get_value("Salary Structure Assignment", filters, "base", order_by="from_date desc")
    )


def get_off_days(employee, start, end, weekly_off_day):
    """Return (weekly_offs, holidays) as sets of dates within the period."""
    weekly, holidays = set(), set()
    holiday_list = None
    try:
        from hrms.hr.utils import get_holiday_list_for_employee
        holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
    except Exception:
        holiday_list = None

    if holiday_list:
        rows = frappe.get_all(
            "Holiday",
            filters={"parent": holiday_list, "holiday_date": ["between", [start, end]]},
            fields=["holiday_date", "weekly_off"],
        )
        for r in rows:
            day = getdate(r.holiday_date)
            if weekly_off_day:
                is_weekly = day.strftime("%A") == weekly_off_day
            else:
                is_weekly = cint(r.weekly_off)
            if is_weekly:
                weekly.add(day)
            else:
                holidays.add(day)

    if weekly_off_day:
        day = start
        while day <= end:
            if day.strftime("%A") == weekly_off_day:
                weekly.add(day)
            day = getdate(add_days(day, 1))

    return weekly, holidays


def get_cutoff(doc, s, end):
    if s.cutoff == "Period End Date":
        return end
    if s.cutoff == "Posting Date" and doc.posting_date:
        return getdate(doc.posting_date)
    return getdate(nowdate())


def nearest_working_day(day, step, start, end, off_days):
    x = getdate(add_days(day, step))
    while start <= x <= end:
        if x not in off_days:
            return x
        x = getdate(add_days(x, step))
    return None


def calculate_deduction_days(doc, method=None):
    """before_validate: calculate earned basic and all day counts as per HR Toolkit Settings.
    (Function name kept for the existing hook.)"""
    if not (doc.employee and doc.start_date and doc.end_date):
        return

    s = get_settings()
    start, end = getdate(doc.start_date), getdate(doc.end_date)
    cutoff = get_cutoff(doc, s, end)

    joining, relieving = frappe.db.get_value(
        "Employee", doc.employee, ["date_of_joining", "relieving_date"]
    )
    joining = getdate(joining) if joining else None
    relieving = getdate(relieving) if relieving else None

    weekly, holidays = get_off_days(doc.employee, start, end, s.weekly_off_day)
    off_days = weekly | holidays
    lwp_types = set(frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name"))

    attendance = {}
    for r in frappe.get_all(
        "Attendance",
        filters={
            "employee": doc.employee,
            "docstatus": 1,
            "attendance_date": ["between", [start, end]],
        },
        fields=["attendance_date", "status", "leave_type"],
    ):
        attendance[getdate(r.attendance_date)] = r

    c = frappe._dict(
        present=0, paid_leave=0, absent=0, unmarked=0, lwp=0, half=0,
        weekly_off=0, holiday=0, sandwich=0, outside=0, future=0,
        service=0, scheduled=0,
    )
    chargeable_dates = set()
    counted_weekly_offs = []

    day = start
    while day <= end:
        is_off = day in off_days
        if not is_off:
            c.scheduled += 1

        in_service = not ((joining and day < joining) or (relieving and day > relieving))
        if not in_service:
            c.outside += 1
        elif day > cutoff:
            c.future += 1
        else:
            c.service += 1
            att = attendance.get(day)
            status = att.status if att else None

            if is_off:
                if status == "Absent" and not s.exclude_holidays:
                    c.absent += 1
                    chargeable_dates.add(day)
                elif day in weekly:
                    c.weekly_off += 1
                    counted_weekly_offs.append(day)
                else:
                    c.holiday += 1
            elif status is None:
                if s.count_unmarked:
                    c.unmarked += 1
                    chargeable_dates.add(day)
                else:
                    c.present += 1
            elif status == "Absent":
                c.absent += 1
                chargeable_dates.add(day)
            elif status == "Half Day":
                c.half += 1
            elif status == "On Leave":
                if s.deduct_lwp and att.leave_type in lwp_types:
                    c.lwp += 1
                    chargeable_dates.add(day)
                else:
                    c.paid_leave += 1
            else:
                c.present += 1

        day = getdate(add_days(day, 1))

    # Sandwich rule: weekly off between two chargeable working days
    if s.sandwich_rule:
        for wo in counted_weekly_offs:
            prev_day = nearest_working_day(wo, -1, start, end, off_days)
            next_day = nearest_working_day(wo, 1, start, end, off_days)
            if prev_day in chargeable_dates and next_day in chargeable_dates:
                c.sandwich += 1

    base = get_base_salary(doc.employee, doc.salary_structure, end)

    if s.method in FIXED_DIVISORS:
        divisor = FIXED_DIVISORS[s.method]
    elif s.method == "Actual Working Days":
        divisor = c.scheduled
    else:
        divisor = date_diff(end, start) + 1

    rate = base / divisor if divisor else 0
    half_value = s.half_day_value if s.count_half_day else 0
    chargeable = c.absent + c.unmarked + c.lwp + c.half * half_value + c.sandwich
    full_period = c.outside == 0 and c.future == 0

    if s.method == "Fixed Monthly Salary":
        chargeable = 0
        payable = divisor if full_period else c.service
    elif full_period:
        if s.method == "Actual Calendar Days":
            if not s.weekly_off_paid:
                chargeable += c.weekly_off - c.sandwich
            if not s.holidays_paid:
                chargeable += c.holiday
        chargeable = min(chargeable, divisor)
        payable = divisor - chargeable
    else:
        payable = c.present + c.paid_leave + c.half * (1 - half_value)
        if s.proration_basis == "Calendar Days":
            if s.weekly_off_paid:
                payable += c.weekly_off - c.sandwich
            if s.holidays_paid:
                payable += c.holiday
        payable = min(payable, divisor)

    earned = base - rate * chargeable if full_period else rate * payable
    earned = flt(min(max(earned, 0), base), s.precision)

    doc.hrt_calculation_method = s.method
    doc.hrt_base_salary = base
    doc.fixed_working_days = divisor
    doc.hrt_daily_rate = flt(rate, 2)
    doc.hrt_full_period = 1 if full_period else 0
    doc.hrt_earned_basic = earned
    doc.hrt_payable_days = flt(payable, 2)
    doc.deduct_days = flt(chargeable, 2)
    doc.hrt_present_days = c.present
    doc.hrt_paid_leave_days = c.paid_leave
    doc.full_absent_days = c.absent
    doc.hrt_unmarked_days = c.unmarked
    doc.hrt_lwp_days = c.lwp
    doc.hrt_half_days = c.half
    doc.hrt_sandwich_days = c.sandwich
    doc.hrt_weekly_off_days = c.weekly_off
    doc.hrt_holiday_days = c.holiday
    doc.hrt_outside_days = c.outside
    doc.hrt_future_days = c.future


def set_fixed_payment_days(doc, method=None):
    """validate: after the standard calculation, show working, absent, LWP and payment days from HR Toolkit."""
    s = get_settings()
    if not s.show_on_slip:
        return
    doc.total_working_days = cint(doc.fixed_working_days)
    doc.absent_days = flt(doc.full_absent_days) + flt(doc.hrt_unmarked_days)
    doc.leave_without_pay = flt(doc.hrt_lwp_days)
    doc.payment_days = flt(doc.hrt_payable_days)
