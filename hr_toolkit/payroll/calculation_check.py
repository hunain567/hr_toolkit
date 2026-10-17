"""Salary calculation test cases for HR Toolkit.

Run:
    bench --site SITE execute hr_toolkit.payroll.calculation_check.run

Creates temporary records (employee, holiday list, leave types, shift types, departments,
overtime policies, overtime entries, checkins, attendance), checks every scenario,
then rolls everything back. Nothing is saved.
"""
import frappe
from frappe.utils import add_days, flt, get_datetime, getdate

from hr_toolkit.payroll.salary_slip import calculate_deduction_days

STRUCTURE = "Standard Salary - SD"
BASE = 50000
RATE26 = BASE / 26
SEP = ("2026-09-01", "2026-09-30")

BASE_SETTINGS = {
    "calculation_method": "26-Day Basis",
    "rounding_precision": 2,
    "show_fixed_days_on_slip": 1,
    "weekly_off_day": "Sunday",
    "weekly_off_paid": 1,
    "sandwich_rule": 0,
    "holidays_paid": 1,
    "exclude_holidays": 1,
    "count_unmarked_as_absent": 0,
    "attendance_cutoff": "Period End Date",
    "deduct_lwp": 1,
    "count_half_day": 0,
    "half_day_value": 0.5,
    "proration_basis": "Working Days",
    "enable_overtime": 1,
    "overtime_from_checkin": 1,
    "overtime_rounding": 1,
    "overtime_min_minutes": 30,
    "overtime_round_minutes": 30,
}


# ---------- helpers ----------

def _set(**values):
    for key, value in values.items():
        frappe.db.set_single_value("HR Toolkit Settings", key, value)
    frappe.clear_document_cache("HR Toolkit Settings", "HR Toolkit Settings")


def _reset():
    _set(**BASE_SETTINGS)


def _leave_type(name, is_lwp):
    if not frappe.db.exists("Leave Type", name):
        frappe.get_doc({"doctype": "Leave Type", "leave_type_name": name, "is_lwp": is_lwp}).insert(
            ignore_permissions=True
        )
    return name


def _shift_type(name, start, end, break_start, break_end, multiplier=0):
    doc = frappe.get_doc({
        "doctype": "Shift Type", "name": name,
        "start_time": start, "end_time": end,
        "hrt_break_start": break_start, "hrt_break_end": break_end,
        "hrt_overtime_multiplier": multiplier,
    })
    doc.insert(ignore_permissions=True)
    return doc


def _remove_policies():
    frappe.db.delete("Overtime Policy Item", {"parenttype": "Overtime Policy"})
    frappe.db.delete("Overtime Policy")


def _policy(ctx, applicable_on, values, multiplier=1, min_salary=0, max_salary=0):
    _remove_policies()
    doc = frappe.get_doc({
        "doctype": "Overtime Policy",
        "policy_name": "HRT Test OT Policy",
        "company": ctx.company,
        "applicable_on": applicable_on,
        "enabled": 1,
        "day_type": "Working Day",
        "rate_multiplier": multiplier,
        "min_salary": min_salary,
        "max_salary": max_salary,
        "items": [{"reference_doctype": applicable_on, "reference_name": v} for v in values],
    })
    doc.insert(ignore_permissions=True)
    return doc


def _ot_entry(ctx, date, hours, shift=None, submit=True):
    doc = frappe.get_doc({
        "doctype": "Overtime Entry",
        "naming_series": "HR-OTE-.YYYY.-",
        "company": ctx.company,
        "overtime_date": date,
        "employees": [{"employee": ctx.emp, "shift": shift, "calculated_hours": hours, "overtime_hours": hours}],
    })
    doc.insert(ignore_permissions=True)
    if submit:
        doc.submit()
    return doc


def _prepare(company, structure):
    ctx = frappe._dict(company=company, structure=structure)
    ctx.lwp = _leave_type("HRT Test LWP", 1)
    ctx.paid = _leave_type("HRT Test Paid Leave", 0)

    hl = frappe.new_doc("Holiday List")
    hl.holiday_list_name = "HRT Test Holidays 2026"
    hl.from_date, hl.to_date = "2026-01-01", "2026-12-31"
    day = getdate("2026-01-01")
    while day <= getdate("2026-12-31"):
        if day.weekday() == 6:
            hl.append("holidays", {"holiday_date": day, "description": "Sunday", "weekly_off": 1})
        day = getdate(add_days(day, 1))
    hl.append("holidays", {"holiday_date": "2026-09-22", "description": "Test Public Holiday", "weekly_off": 0})
    hl.insert(ignore_permissions=True)

    gender = frappe.db.get_value("Gender", {}, "name")
    emp = frappe.get_doc({
        "doctype": "Employee",
        "first_name": "HRT Test Employee",
        "gender": gender,
        "date_of_birth": "1990-01-01",
        "date_of_joining": "2026-01-01",
        "company": company,
        "status": "Active",
        "holiday_list": hl.name,
    }).insert(ignore_permissions=True)
    ctx.emp = emp.name

    ssa = frappe.get_doc({
        "doctype": "Salary Structure Assignment",
        "employee": emp.name,
        "salary_structure": structure,
        "company": company,
        "from_date": "2026-01-01",
        "base": BASE,
    })
    ssa.insert(ignore_permissions=True)
    ssa.submit()

    ctx.morning = _shift_type("HRT Test Morning", "08:00:00", "17:00:00", "13:00:00", "14:00:00").name
    ctx.evening = _shift_type("HRT Test Evening", "14:00:00", "22:00:00", "18:00:00", "18:30:00", 0)
    ctx.night = _shift_type("HRT Test Night", "20:00:00", "05:00:00", "00:00:00", "01:00:00", 2)
    return ctx


def _att(ctx, date, status, leave_type=None, shift=None):
    a = frappe.get_doc({
        "doctype": "Attendance",
        "employee": ctx.emp,
        "company": ctx.company,
        "attendance_date": date,
        "status": status,
        "leave_type": leave_type,
        "shift": shift,
    })
    a.flags.ignore_permissions = True
    a.insert()
    a.submit()
    return a


def _checkin(ctx, time):
    frappe.get_doc({
        "doctype": "Employee Checkin", "employee": ctx.emp, "time": time, "device_id": "HRT-TEST",
    }).insert(ignore_permissions=True)


def _clear(ctx):
    frappe.db.delete("Attendance", {"employee": ctx.emp})
    frappe.db.delete("Employee Checkin", {"employee": ctx.emp})
    parents = frappe.get_all("Overtime Entry Detail", filters={"employee": ctx.emp}, pluck="parent")
    frappe.db.delete("Overtime Entry Detail", {"employee": ctx.emp})
    for p in set(parents):
        frappe.db.delete("Overtime Entry", {"name": p})


def _emp(ctx, **values):
    frappe.db.set_value("Employee", ctx.emp, values, update_modified=False)


def _slip(ctx, start, end):
    return frappe.get_doc({
        "doctype": "Salary Slip",
        "employee": ctx.emp,
        "company": ctx.company,
        "payroll_frequency": "Monthly",
        "start_date": start,
        "end_date": end,
        "posting_date": end,
        "salary_structure": ctx.structure,
    })


def _calc(ctx, start, end):
    slip = _slip(ctx, start, end)
    calculate_deduction_days(slip)
    return slip


def _check(results, name, slip, expected, actual=None):
    expected = flt(expected, 2)
    actual = flt(slip.hrt_earned_basic if actual is None else actual, 2)
    results.append(frappe._dict(
        name=name, expected=expected, actual=actual, ok=abs(actual - expected) < 0.02,
        payable=slip.hrt_payable_days, chargeable=slip.deduct_days,
    ))


def _blocked(fn):
    try:
        fn()
    except frappe.ValidationError:
        frappe.clear_messages()
        return 1
    return 0


# ---------- salary cases ----------

def _cases(ctx, r):
    _reset()
    _remove_policies()

    _check(r, "T1 Full month, no absence (Sep)", _calc(ctx, *SEP), BASE)
    _att(ctx, "2026-09-01", "Absent")
    _att(ctx, "2026-09-02", "Absent")
    _check(r, "T2 Full month, 2 absents", _calc(ctx, *SEP), BASE - 2 * RATE26)
    _att(ctx, "2026-09-03", "Absent")
    _check(r, "T3 Full month, 3 absents", _calc(ctx, *SEP), BASE - 3 * RATE26)
    _clear(ctx)

    _emp(ctx, date_of_joining="2026-02-01", relieving_date="2026-02-13")
    _check(r, "T4a Join 1 Feb, leave 13 Feb, Working Days basis", _calc(ctx, "2026-02-01", "2026-02-28"), RATE26 * 11)
    _set(proration_basis="Calendar Days")
    _check(r, "T4b Join 1 Feb, leave 13 Feb, Calendar Days basis", _calc(ctx, "2026-02-01", "2026-02-28"), RATE26 * 13)
    _reset()

    _emp(ctx, date_of_joining="2026-01-01", relieving_date="2026-09-15")
    _check(r, "T5 Leave 15 Sep, 13 payable days", _calc(ctx, *SEP), RATE26 * 13)
    _emp(ctx, date_of_joining="2026-01-01", relieving_date=None)

    months = [
        ("Feb (28 days)", "2026-02-01", "2026-02-28", "2026-02-03"),
        ("Apr (30 days)", "2026-04-01", "2026-04-30", "2026-04-07"),
        ("Jan (31 days)", "2026-01-01", "2026-01-31", "2026-01-06"),
    ]
    for label, start, end, absent_day in months:
        _check(r, f"T6 Full month {label}", _calc(ctx, start, end), BASE)
    for label, start, end, absent_day in months:
        _att(ctx, absent_day, "Absent")
        _check(r, f"T6 {label}, 1 absent", _calc(ctx, start, end), BASE - RATE26)
    _clear(ctx)

    _check(r, "T7a Sep: 4 Sundays + holiday 22 Sep, no absence", _calc(ctx, *SEP), BASE)
    _set(calculation_method="Actual Calendar Days", weekly_off_paid=0)
    _check(r, "T7b Calendar Days method, Sundays unpaid", _calc(ctx, *SEP), BASE - BASE / 30 * 4)
    _reset()
    _att(ctx, "2026-09-05", "Absent")
    _att(ctx, "2026-09-07", "Absent")
    _check(r, "T7c Absent Sat 5 + Mon 7 Sep, sandwich off", _calc(ctx, *SEP), BASE - 2 * RATE26)
    _set(sandwich_rule=1)
    _check(r, "T7d Absent Sat 5 + Mon 7 Sep, sandwich on", _calc(ctx, *SEP), BASE - 3 * RATE26)
    _reset()
    _clear(ctx)
    _att(ctx, "2026-09-08", "On Leave", ctx.lwp)
    _att(ctx, "2026-09-09", "On Leave", ctx.paid)
    _check(r, "T7e 1 LWP + 1 paid leave", _calc(ctx, *SEP), BASE - RATE26)
    _clear(ctx)

    _emp(ctx, date_of_joining="2026-09-16")
    _check(r, "T8 Join 16 Sep (12 working days, holiday excluded)", _calc(ctx, *SEP), RATE26 * 12)
    _emp(ctx, date_of_joining="2026-01-01")

    _att(ctx, "2026-09-01", "Absent")
    _att(ctx, "2026-09-02", "Absent")
    slip = _slip(ctx, *SEP)
    slip.insert(ignore_permissions=True)
    basic = 0
    for row in slip.earnings:
        if row.salary_component == "Basic":
            basic = row.amount
    _check(r, "T9 Salary Slip: Basic row = Earned Basic", slip, BASE - 2 * RATE26, actual=basic)
    _clear(ctx)


# ---------- overtime cases ----------

def _overtime_cases(ctx, r):
    _reset()
    _clear(ctx)
    _emp(ctx, default_shift=ctx.morning)
    hourly = RATE26 / 8

    _ot_entry(ctx, "2026-09-03", 4)
    _ot_entry(ctx, "2026-09-10", 6)
    _ot_entry(ctx, "2026-09-11", 5, submit=False)  # draft, must not count

    _policy(ctx, "Employee", [ctx.emp], multiplier=1)
    slip = _calc(ctx, *SEP)
    _check(r, "T10a Submitted entries only, single rate, 10 h", slip, hourly * 10, actual=slip.hrt_overtime_amount)
    _policy(ctx, "Employee", [ctx.emp], multiplier=2)
    slip = _calc(ctx, *SEP)
    _check(r, "T10b Double rate, 10 h", slip, hourly * 20, actual=slip.hrt_overtime_amount)
    _check(r, "T10c Basic not affected by overtime", slip, BASE)

    slip = _slip(ctx, *SEP)
    slip.check_existing = lambda: None  # test only, T9 already created a September slip
    slip.insert(ignore_permissions=True)
    ot = 0
    for row in slip.earnings:
        if row.salary_component == "Over Time":
            ot = row.amount
    _check(r, "T10d Salary Slip: Over Time row = Overtime Amount", slip, hourly * 20, actual=ot)
    _clear(ctx)


def _shift_cases(ctx, r):
    _reset()
    _clear(ctx)
    _policy(ctx, "Employee", [ctx.emp], multiplier=1)

    _ot_entry(ctx, "2026-09-03", 2, shift=ctx.evening.name)
    _ot_entry(ctx, "2026-09-10", 2, shift=ctx.night.name)

    slip = _calc(ctx, *SEP)
    _check(r, "T11a Evening break 18:00-18:30 = 30 minutes", slip, 30, actual=ctx.evening.hrt_break_minutes)
    _check(r, "T11b Evening 14:00-22:00 - 30 min = 7.5 h", slip, 7.5, actual=ctx.evening.hrt_shift_hours)
    _check(r, "T11c Night 20:00-05:00 - 1 h break = 8 h", slip, 8, actual=ctx.night.hrt_shift_hours)
    expected = RATE26 / 7.5 * 2 * 1 + RATE26 / 8 * 2 * 2
    _check(r, "T11d OT: Evening 2 h policy rate + Night 2 h shift double", slip, expected, actual=slip.hrt_overtime_amount)
    _clear(ctx)

    _emp(ctx, default_shift=None)
    _ot_entry(ctx, "2026-09-03", 2)
    _check(r, "T12 OT without any shift is blocked", slip, 1, actual=_blocked(lambda: _calc(ctx, *SEP)))
    _clear(ctx)
    _emp(ctx, default_shift=ctx.morning)


def _department(name, company):
    return frappe.get_doc({
        "doctype": "Department", "department_name": name,
        "parent_department": "All Departments", "company": company,
    }).insert(ignore_permissions=True).name


def _eligibility_cases(ctx, r):
    _reset()
    _clear(ctx)
    _remove_policies()

    production = _department("HRT Test Production", ctx.company)
    office = _department("HRT Test Office", ctx.company)
    designation = frappe.get_doc({"doctype": "Designation", "designation_name": "HRT Test Operator"}).insert(
        ignore_permissions=True
    ).name
    _emp(ctx, default_shift=ctx.morning, department=office, designation=designation)
    _ot_entry(ctx, "2026-09-03", 4)
    ot = RATE26 / 8 * 4

    slip = _calc(ctx, *SEP)
    _check(r, "T13a No Overtime Policy: 0", slip, 0, actual=slip.hrt_overtime_amount)

    _policy(ctx, "Department", [production])
    slip = _calc(ctx, *SEP)
    _check(r, "T13b Office not in policy departments: 0", slip, 0, actual=slip.hrt_overtime_amount)

    _emp(ctx, department=production)
    slip = _calc(ctx, *SEP)
    _check(r, "T13c Production in policy departments", slip, ot, actual=slip.hrt_overtime_amount)

    _policy(ctx, "Department", [production], min_salary=60000)
    slip = _calc(ctx, *SEP)
    _check(r, "T13d Salary 50k below minimum 60k: 0", slip, 0, actual=slip.hrt_overtime_amount)

    _policy(ctx, "Department", [production], max_salary=40000)
    slip = _calc(ctx, *SEP)
    _check(r, "T13e Salary 50k above maximum 40k: 0", slip, 0, actual=slip.hrt_overtime_amount)

    _policy(ctx, "Department", [production], max_salary=60000)
    slip = _calc(ctx, *SEP)
    _check(r, "T13f Salary 50k within 0-60k: eligible", slip, ot, actual=slip.hrt_overtime_amount)

    _policy(ctx, "Designation", [designation])
    slip = _calc(ctx, *SEP)
    _check(r, "T13g Designation based policy: eligible", slip, ot, actual=slip.hrt_overtime_amount)

    policy = _policy(ctx, "Department", [production])
    policy.items = []
    added = policy.get_all_items()
    names = [row.reference_name for row in policy.items]
    found = 1 if (production in names and office in names and added >= 2) else 0
    _check(r, "T13h Get Departments adds all company departments", slip, 1, actual=found)
    _clear(ctx)


def _checkin_cases(ctx, r):
    _reset()
    _clear(ctx)
    _emp(ctx, default_shift=ctx.morning)
    _policy(ctx, "Employee", [ctx.emp], multiplier=1)
    slip = _calc(ctx, *SEP)

    # Attendance (information): morning 07:55-19:05 = 11h10 - 1h break - 8h = 2h10 -> 2 h
    _checkin(ctx, "2026-09-15 07:55:00")
    _checkin(ctx, "2026-09-15 19:05:00")
    a = _att(ctx, "2026-09-15", "Present")
    _check(r, "T14a Attendance from checkin: 2h10 rounded to 2 h", slip, 2, actual=a.overtime_hours)

    # Night 19:55 - next day 07:05 = 11h10 - 1h - 8h -> 2 h
    _checkin(ctx, "2026-09-16 19:55:00")
    _checkin(ctx, "2026-09-17 07:05:00")
    a = _att(ctx, "2026-09-16", "Present", shift=ctx.night.name)
    _check(r, "T14b Night shift across midnight: 2 h", slip, 2, actual=a.overtime_hours)

    # 07:55-17:20 = 25 min, below 30 min minimum -> 0
    _checkin(ctx, "2026-09-18 07:55:00")
    _checkin(ctx, "2026-09-18 17:20:00")
    a = _att(ctx, "2026-09-18", "Present")
    _check(r, "T14c 25 min below 30 min minimum: 0", slip, 0, actual=a.overtime_hours)

    slip = _calc(ctx, *SEP)
    _check(r, "T14d Attendance overtime alone does not hit salary", slip, 0, actual=slip.hrt_overtime_amount)

    # Overtime Entry: Get Employees on 21 Sep (07:55-19:05) -> 2 h, submit -> salary
    _checkin(ctx, "2026-09-21 07:55:00")
    _checkin(ctx, "2026-09-21 19:05:00")
    entry = frappe.get_doc({
        "doctype": "Overtime Entry", "naming_series": "HR-OTE-.YYYY.-",
        "company": ctx.company, "overtime_date": "2026-09-21",
    })
    entry.get_employees()
    row = None
    for d in entry.employees:
        if d.employee == ctx.emp:
            row = d
    _check(r, "T15a Get Employees: calculated 2 h from checkin", slip, 2, actual=row.calculated_hours if row else -1)
    entry.set("employees", [row] if row else [])
    entry.insert(ignore_permissions=True)
    entry.submit()
    slip = _calc(ctx, *SEP)
    _check(r, "T15b Submitted Overtime Entry hits salary", slip, RATE26 / 8 * 2, actual=slip.hrt_overtime_amount)

    dup = frappe.get_doc({
        "doctype": "Overtime Entry", "naming_series": "HR-OTE-.YYYY.-",
        "company": ctx.company, "overtime_date": "2026-09-21",
        "employees": [{"employee": ctx.emp, "calculated_hours": 2, "overtime_hours": 2}],
    })
    _check(r, "T16 Second entry same employee same date is blocked", slip, 1,
           actual=_blocked(lambda: (dup.insert(ignore_permissions=True), dup.submit())))
    _clear(ctx)


def run(company=None, structure=STRUCTURE):
    company = company or frappe.db.get_value("Salary Structure", structure, "company")
    results, error = [], None
    try:
        ctx = _prepare(company, structure)
        _cases(ctx, results)
        _overtime_cases(ctx, results)
        _shift_cases(ctx, results)
        _eligibility_cases(ctx, results)
        _checkin_cases(ctx, results)
        _rounding_cases(ctx, results)
        _entry_amount_cases(ctx, results)
        _bonus_cases(ctx, results)
        _checkin_tool_cases(ctx, results)
        _salary_revision_cases(ctx, results)
    except Exception:
        error = frappe.get_traceback()
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("HR Toolkit Settings", "HR Toolkit Settings")

    for x in results:
        print(
            f"{'PASS' if x.ok else 'FAIL'} | {x.name:58} | expected {x.expected:>10,.2f}"
            f" | actual {x.actual:>10,.2f} | payable {x.payable} | chargeable {x.chargeable}"
        )
    passed = len([x for x in results if x.ok])
    print(f"\n{passed}/{len(results)} passed. All test data rolled back.")
    if error:
        print("\nSTOPPED WITH ERROR:\n" + error)


def _rounding_cases(ctx, r):
    from hr_toolkit.payroll.attendance import compute_overtime

    _reset()
    _set(overtime_rounding=1, overtime_round_minutes=60, overtime_min_minutes=30)
    _clear(ctx)
    slip = _calc(ctx, *SEP)

    # Morning 08:00-17:00, break 13-14. In 08:00, out as below.
    table = [
        ("2026-09-23", "17:59:00", 0, "T17a Out 5:59 (59 min) rounding on"),
        ("2026-09-24", "18:01:00", 1, "T17b Out 6:01 (1 h 1 min) rounding on"),
        ("2026-09-25", "19:10:00", 2, "T17c Out 7:10 (2 h 10 min) rounding on"),
        ("2026-09-26", "19:59:00", 2, "T17d Out 7:59 (2 h 59 min) rounding on"),
        ("2026-09-28", "20:59:00", 3, "T17e Out 8:59 (3 h 59 min) rounding on"),
    ]
    for date, out, expected, name in table:
        _checkin(ctx, f"{date} 08:00:00")
        _checkin(ctx, f"{date} {out}")
        result = compute_overtime(ctx.emp, date, ctx.morning)
        _check(r, name, slip, expected, actual=result.overtime_hours if result else -1)

    _set(overtime_rounding=0)
    result = compute_overtime(ctx.emp, "2026-09-25", ctx.morning)
    _check(r, "T17f Out 7:10 rounding off = 2.17", slip, 2.17, actual=result.overtime_hours if result else -1)
    result = compute_overtime(ctx.emp, "2026-09-24", ctx.morning)
    _check(r, "T17g Out 6:01 rounding off = 1.02", slip, 1.02, actual=result.overtime_hours if result else -1)
    _clear(ctx)


def _entry_amount_cases(ctx, r):
    _reset()
    _clear(ctx)
    _emp(ctx, default_shift=ctx.morning)
    _policy(ctx, "Employee", [ctx.emp], multiplier=1)
    slip = _calc(ctx, *SEP)

    entry = _ot_entry(ctx, "2026-09-29", 2, submit=False)
    row = entry.employees[0]
    _check(r, "T18a Overtime Entry: Monthly Salary", slip, BASE, actual=row.monthly_salary)
    _check(r, "T18b Overtime Entry: Hourly Rate 50,000/26/8", slip, RATE26 / 8, actual=row.hourly_rate)
    _check(r, "T18c Overtime Entry: Amount 2 h single", slip, RATE26 / 8 * 2, actual=row.overtime_amount)

    _remove_policies()
    entry.save()
    _check(r, "T18d Not eligible employee: Amount 0", slip, 0, actual=entry.employees[0].overtime_amount)
    _clear(ctx)


def _bonus_cases(ctx, r):
    from hr_toolkit.payroll.bonus import get_bonus_row

    _reset()
    _clear(ctx)
    slip = _calc(ctx, *SEP)

    expense = frappe.db.get_value("Account", {"company": ctx.company, "root_type": "Expense", "is_group": 0}, "name")
    credit = frappe.db.get_value("Account", {"company": ctx.company, "account_type": "Cash", "is_group": 0}, "name") \
        or frappe.db.get_value("Account", {"company": ctx.company, "root_type": "Liability", "is_group": 0, "account_type": ["!=", "Payable"]}, "name")
    policy = frappe.get_doc({
        "doctype": "Bonus Policy", "policy_name": "HRT Test Bonus", "company": ctx.company,
        "enabled": 1, "min_service_months": 6, "bonus_percent": 50,
        "expense_account": expense, "credit_account": credit,
    }).insert(ignore_permissions=True)

    _emp(ctx, date_of_joining="2026-04-10", relieving_date=None)
    row = get_bonus_row(ctx.emp, "2026-10-09", policy)
    _check(r, "T19a Join 10 Apr, bonus 9 Oct (5 months): 0", slip, 0, actual=row.calculated_amount)
    row = get_bonus_row(ctx.emp, "2026-10-10", policy)
    _check(r, "T19b Join 10 Apr, bonus 10 Oct (6 months): 50%", slip, BASE * 0.5, actual=row.calculated_amount)

    _emp(ctx, relieving_date="2026-10-05")
    row = get_bonus_row(ctx.emp, "2026-10-10", policy)
    _check(r, "T19c Left before bonus date: 0", slip, 0, actual=row.calculated_amount)
    _emp(ctx, relieving_date=None)

    entry = frappe.get_doc({
        "doctype": "Bonus Entry", "naming_series": "HR-BON-.YYYY.-", "company": ctx.company,
        "bonus_date": "2026-10-10", "bonus_policy": policy.name,
        "expense_account": expense, "credit_account": credit,
        "employees": [{"employee": ctx.emp, "bonus_amount": BASE * 0.5}],
    })
    entry.insert(ignore_permissions=True)
    entry.submit()
    je_debit = frappe.db.get_value("Journal Entry", entry.journal_entry, "total_debit") if entry.journal_entry else 0
    _check(r, "T19d Submit creates Journal Entry for 25,000", slip, BASE * 0.5, actual=je_debit)

    dup = frappe.get_doc({
        "doctype": "Bonus Entry", "naming_series": "HR-BON-.YYYY.-", "company": ctx.company,
        "bonus_date": "2026-10-10", "bonus_policy": policy.name,
        "expense_account": expense, "credit_account": credit,
        "employees": [{"employee": ctx.emp, "bonus_amount": BASE * 0.5}],
    })
    _check(r, "T19e Second bonus same employee same date is blocked", slip, 1,
           actual=_blocked(lambda: dup.insert(ignore_permissions=True)))

    _emp(ctx, date_of_joining="2026-01-01")


def _checkin_tool_cases(ctx, r):
    from hr_toolkit.hr_toolkit.doctype.checkin_adjustment_tool.checkin_adjustment_tool import (
        get_month_checkins,
        save_month_checkins,
    )

    _reset()
    _clear(ctx)
    _emp(ctx, default_shift=ctx.morning)
    slip = _calc(ctx, *SEP)

    # Only IN at 07:58 on 30 Sep -> Missing OUT
    _checkin(ctx, "2026-09-30 07:58:00")
    rows = get_month_checkins(ctx.emp, "2026-09-28", "2026-09-30")
    row = [d for d in rows if str(d["date"]) == "2026-09-30"][0]
    _check(r, "T20a Month view shows Missing OUT", slip, 1, actual=1 if "Missing OUT" in row["remarks"] else 0)

    # Correct IN to 08:00 and add OUT 19:05 -> 08:00-19:05 = 11h05 - 1h - 8h = 2h05 -> 2 h
    row["in_time"] = "08:00:00"
    row["out_time"] = "19:05:00"
    res = save_month_checkins(ctx.emp, [row], 1)
    in_time = frappe.db.get_value("Employee Checkin", row["in_checkin"], "time")
    _check(r, "T20b Existing IN updated to 08:00", slip, 1,
           actual=1 if in_time and get_datetime(in_time).strftime("%H:%M") == "08:00" else 0)
    ot = frappe.db.get_value("Attendance", {"employee": ctx.emp, "attendance_date": "2026-09-30", "docstatus": 1}, "overtime_hours")
    _check(r, "T20c OUT created, Present attendance with 2 h OT", slip, 2, actual=ot or -1)

    # Clear OUT -> deleted
    rows = get_month_checkins(ctx.emp, "2026-09-30", "2026-09-30")
    row = rows[0]
    row["out_time"] = None
    res = save_month_checkins(ctx.emp, [row], 0)
    _check(r, "T20d Cleared OUT time deletes the checkin", slip, 1, actual=res["deleted"])
    _clear(ctx)


def _salary_revision_cases(ctx, r):
    _reset()
    _clear(ctx)
    _emp(ctx, date_of_joining="2026-01-01", relieving_date=None)
    slip = _calc(ctx, *SEP)

    rev = frappe.get_doc({
        "doctype": "Salary Revision", "naming_series": "HR-SREV-.YYYY.-",
        "company": ctx.company, "effective_date": "2026-10-01",
        "increment_type": "Percentage", "increment_value": 10,
        "employees": [{"employee": ctx.emp, "new_salary": 1}],
    })
    rev.apply_increment = rev.apply_increment  # whitelisted method also works in code
    rev.validate()  # fills current salary
    _check(r, "T21a Current Salary fetched", slip, BASE, actual=rev.employees[0].current_salary)
    rev.apply_increment()
    _check(r, "T21b Apply 10% to all: 55,000", slip, 55000, actual=rev.employees[0].new_salary)

    rev.insert(ignore_permissions=True)
    rev.submit()
    base = frappe.db.get_value("Salary Structure Assignment", rev.employees[0].salary_structure_assignment, "base")
    _check(r, "T21c Submit creates assignment with 55,000", slip, 55000, actual=base)
    _check(r, "T21d Employee Salary updated to 55,000", slip, 55000,
           actual=frappe.db.get_value("Employee", ctx.emp, "hrt_salary"))

    rev.cancel()
    _check(r, "T21e Cancel restores Employee Salary 50,000", slip, BASE,
           actual=frappe.db.get_value("Employee", ctx.emp, "hrt_salary"))

    dup = frappe.get_doc({
        "doctype": "Salary Revision", "naming_series": "HR-SREV-.YYYY.-",
        "company": ctx.company, "effective_date": "2026-10-01",
        "employees": [{"employee": ctx.emp, "new_salary": 55000}, {"employee": ctx.emp, "new_salary": 56000}],
    })
    _check(r, "T21f Same employee twice in one document is blocked", slip, 1,
           actual=_blocked(lambda: dup.insert(ignore_permissions=True)))
