import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, formatdate, getdate, nowdate

from hr_toolkit.payroll.shift import find_assignment, get_shift_assignments, get_shift_types

FIXED_DIVISORS = {"26-Day Basis": 26, "30-Day Basis": 30}

# Overtime Policy "Applicable On" -> Employee field
POLICY_EMPLOYEE_FIELD = {
    "Department": "department",
    "Designation": "designation",
    "Employee Grade": "grade",
    "Employee": "name",
}


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
        enable_overtime=cint(s.get("enable_overtime")),
    )


def get_overtime_policy(s, employee, base):
    """Return (policy, reason). Day Type is reserved: Working Day policies are checked first."""
    if not s.enable_overtime:
        return None, "Overtime disabled"

    policies = frappe.get_all(
        "Overtime Policy",
        filters={"company": employee.company, "enabled": 1},
        fields=["name", "applicable_on", "day_type", "rate_multiplier", "min_salary", "max_salary"],
        order_by="modified desc",
    )
    policies.sort(key=lambda p: 0 if p.day_type == "Working Day" else 1)

    for p in policies:
        value = employee.get(POLICY_EMPLOYEE_FIELD.get(p.applicable_on))
        if not value:
            continue
        if not frappe.db.exists(
            "Overtime Policy Item", {"parent": p.name, "parenttype": "Overtime Policy", "reference_name": value}
        ):
            continue
        if flt(p.min_salary) and base < flt(p.min_salary):
            return None, f"Not eligible (salary below minimum, {p.name})"
        if flt(p.max_salary) and base > flt(p.max_salary):
            return None, f"Not eligible (salary above maximum, {p.name})"
        return p, f"Eligible ({p.name})"

    return None, "Not eligible (no matching Overtime Policy)"


def get_submitted_overtime(employee, start, end):
    """{date: [rows]} from submitted Overtime Entry."""
    out = {}
    for r in frappe.db.sql(
        """select e.overtime_date, d.overtime_hours, d.shift
           from `tabOvertime Entry Detail` d
           inner join `tabOvertime Entry` e on e.name = d.parent
           where e.docstatus = 1 and d.employee = %s and e.overtime_date between %s and %s""",
        (employee, start, end),
        as_dict=True,
    ):
        out.setdefault(getdate(r.overtime_date), []).append(r)
    return out


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


def is_full_month_period(start, end):
    """True when the slip covers a complete monthly payroll period
    (e.g. 1 Sep - 30 Sep, or 26 Sep - 25 Oct)."""
    return end >= getdate(add_days(add_months(start, 1), -1))


def nearest_working_day(day, step, start, end, off_days):
    x = getdate(add_days(day, step))
    while start <= x <= end:
        if x not in off_days:
            return x
        x = getdate(add_days(x, step))
    return None


def calculate_deduction_days(doc, method=None):
    """before_validate: calculate earned basic, overtime and all day counts as per HR Toolkit Settings.
    (Function name kept for the existing hook.)"""
    if not (doc.employee and doc.start_date and doc.end_date):
        return

    s = get_settings()
    start, end = getdate(doc.start_date), getdate(doc.end_date)
    cutoff = get_cutoff(doc, s, end)

    employee = frappe.db.get_value(
        "Employee",
        doc.employee,
        ["name", "company", "date_of_joining", "relieving_date", "default_shift",
         "department", "designation", "grade"],
        as_dict=True,
    )
    joining = getdate(employee.date_of_joining) if employee.date_of_joining else None
    relieving = getdate(employee.relieving_date) if employee.relieving_date else None
    default_shift = employee.default_shift

    base = get_base_salary(doc.employee, doc.salary_structure, end)
    policy, ot_reason = get_overtime_policy(s, employee, base)

    weekly, holidays = get_off_days(doc.employee, start, end, s.weekly_off_day)
    off_days = weekly | holidays
    lwp_types = set(frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name"))

    overtime = get_submitted_overtime(doc.employee, start, end) if s.enable_overtime else {}
    shift_types = get_shift_types() if policy and overtime else {}
    assignments = get_shift_assignments(doc.employee, start, end) if policy and overtime else []

    attendance = {}
    for r in frappe.get_all(
        "Attendance",
        filters={
            "employee": doc.employee,
            "docstatus": 1,
            "attendance_date": ["between", [start, end]],
        },
        fields=["attendance_date", "status", "leave_type", "shift"],
    ):
        attendance[getdate(r.attendance_date)] = r

    c = frappe._dict(
        present=0, paid_leave=0, absent=0, unmarked=0, lwp=0, half=0,
        weekly_off=0, holiday=0, sandwich=0, outside=0, future=0,
        service=0, scheduled=0, overtime_hours=0, overtime_units=0,
    )
    chargeable_dates = set()
    counted_weekly_offs = []
    missing_shift = []

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

            # Overtime from submitted Overtime Entry, using the Shift Type of this day
            for ot in overtime.get(day, []):
                hours = flt(ot.overtime_hours)
                if hours <= 0:
                    continue
                c.overtime_hours += hours
                if policy:
                    shift = ot.shift or (att.shift if att else None) or find_assignment(day, assignments) or default_shift
                    st = shift_types.get(shift)
                    if not st or st.hours <= 0:
                        missing_shift.append(day)
                    else:
                        multiplier = st.multiplier if st.multiplier > 0 else flt(policy.rate_multiplier) or 1
                        c.overtime_units += hours * multiplier / st.hours

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

    if missing_shift:
        frappe.throw(
            _("Overtime cannot be calculated for {0}: no Shift found on {1}. "
              "Please set a Default Shift on the Employee, a Shift Assignment, or a Shift on the Overtime Entry.").format(
                doc.employee, ", ".join(formatdate(d) for d in missing_shift)
            ),
            title=_("Shift Not Found"),
        )

    # Sandwich rule: weekly off between two chargeable working days
    if s.sandwich_rule:
        for wo in counted_weekly_offs:
            prev_day = nearest_working_day(wo, -1, start, end, off_days)
            next_day = nearest_working_day(wo, 1, start, end, off_days)
            if prev_day in chargeable_dates and next_day in chargeable_dates:
                c.sandwich += 1

    if s.method in FIXED_DIVISORS:
        divisor = FIXED_DIVISORS[s.method]
    elif s.method == "Actual Working Days":
        divisor = c.scheduled
    else:
        divisor = date_diff(end, start) + 1

    rate = base / divisor if divisor else 0
    half_value = s.half_day_value if s.count_half_day else 0
    chargeable = c.absent + c.unmarked + c.lwp + c.half * half_value + c.sandwich

    # Full period only when the slip covers a complete month, the employee was
    # in service for all of it and no day falls after the attendance cut-off.
    full_period = is_full_month_period(start, end) and c.outside == 0 and c.future == 0

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

    # Overtime amount = Daily Rate x sum(OT hours x multiplier / shift hours)
    overtime_amount = flt(rate * c.overtime_units, s.precision) if policy else 0
    if not shift_types and default_shift:
        shift_types = get_shift_types()
    default_st = shift_types.get(default_shift)
    default_hours = default_st.hours if default_st and default_st.hours > 0 else 0

    doc.hrt_calculation_method = s.method
    doc.hrt_base_salary = base
    doc.fixed_working_days = divisor
    doc.hrt_daily_rate = flt(rate, 2)
    doc.hrt_full_period = 1 if full_period else 0
    doc.hrt_earned_basic = earned
    doc.hrt_hourly_rate = flt(rate / default_hours, 2) if default_hours else 0
    doc.hrt_overtime_hours = flt(c.overtime_hours, 2)
    doc.hrt_overtime_amount = overtime_amount
    doc.hrt_overtime_eligibility = ot_reason
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
