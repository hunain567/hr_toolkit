"""Salary calculation test cases for HR Toolkit.

Run:
    bench --site SITE execute hr_toolkit.payroll.calculation_check.run

Creates a temporary employee, holiday list, leave types and attendance,
checks every scenario, then rolls everything back. Nothing is saved.
"""
import frappe
from frappe.utils import add_days, flt, getdate

from hr_toolkit.payroll.salary_slip import calculate_deduction_days

STRUCTURE = "Standard Salary - SD"
BASE = 50000
RATE26 = BASE / 26

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
}


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
    return ctx


def _att(ctx, date, status, leave_type=None):
    a = frappe.get_doc({
        "doctype": "Attendance",
        "employee": ctx.emp,
        "company": ctx.company,
        "attendance_date": date,
        "status": status,
        "leave_type": leave_type,
    })
    a.flags.ignore_permissions = True
    a.insert()
    a.submit()


def _clear(ctx):
    frappe.db.delete("Attendance", {"employee": ctx.emp})


def _emp_dates(ctx, joining, relieving=None):
    frappe.db.set_value(
        "Employee", ctx.emp, {"date_of_joining": joining, "relieving_date": relieving}, update_modified=False
    )


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


def _cases(ctx, r):
    SEP = ("2026-09-01", "2026-09-30")
    _reset()

    # Test 1, 2, 3: full month
    _check(r, "T1 Full month, no absence (Sep)", _calc(ctx, *SEP), BASE)
    _att(ctx, "2026-09-01", "Absent")
    _att(ctx, "2026-09-02", "Absent")
    _check(r, "T2 Full month, 2 absents", _calc(ctx, *SEP), BASE - 2 * RATE26)
    _att(ctx, "2026-09-03", "Absent")
    _check(r, "T3 Full month, 3 absents", _calc(ctx, *SEP), BASE - 3 * RATE26)
    _clear(ctx)

    # Test 4: join 1 Feb, leave 13 Feb (2 Sundays, 11 working days)
    _emp_dates(ctx, "2026-02-01", "2026-02-13")
    _check(r, "T4a Join 1 Feb, leave 13 Feb, Working Days basis", _calc(ctx, "2026-02-01", "2026-02-28"), RATE26 * 11)
    _set(proration_basis="Calendar Days")
    _check(r, "T4b Join 1 Feb, leave 13 Feb, Calendar Days basis", _calc(ctx, "2026-02-01", "2026-02-28"), RATE26 * 13)
    _reset()

    # Test 5: 13 payable working days (leave 15 Sep)
    _emp_dates(ctx, "2026-01-01", "2026-09-15")
    _check(r, "T5 Leave 15 Sep, 13 payable days", _calc(ctx, *SEP), RATE26 * 13)
    _emp_dates(ctx, "2026-01-01", None)

    # Test 6: 28, 30 and 31 day months
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

    # Test 7: weekly off, public holiday, sandwich, leave
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

    # Test 8: join mid-month, holiday inside service period not double counted
    _emp_dates(ctx, "2026-09-16", None)
    _check(r, "T8 Join 16 Sep (12 working days, holiday excluded)", _calc(ctx, *SEP), RATE26 * 12)
    _emp_dates(ctx, "2026-01-01", None)

    # Test 9: real Salary Slip insert, Basic row must equal Earned Basic
    _att(ctx, "2026-09-01", "Absent")
    _att(ctx, "2026-09-02", "Absent")
    slip = _slip(ctx, *SEP)
    slip.insert(ignore_permissions=True)
    basic = 0
    for row in slip.earnings:
        if row.salary_component == "Basic":
            basic = row.amount
    _check(r, "T9 Salary Slip: Basic row = Earned Basic", slip, BASE - 2 * RATE26, actual=basic)


def run(company=None, structure=STRUCTURE):
    company = company or frappe.db.get_value("Salary Structure", structure, "company")
    results, error = [], None
    try:
        ctx = _prepare(company, structure)
        _cases(ctx, results)
    except Exception:
        error = frappe.get_traceback()
    finally:
        frappe.db.rollback()
        frappe.clear_document_cache("HR Toolkit Settings", "HR Toolkit Settings")

    for x in results:
        print(
            f"{'PASS' if x.ok else 'FAIL'} | {x.name:55} | expected {x.expected:>10,.2f}"
            f" | actual {x.actual:>10,.2f} | payable {x.payable} | chargeable {x.chargeable}"
        )
    passed = len([x for x in results if x.ok])
    print(f"\n{passed}/{len(results)} passed. All test data rolled back.")
    if error:
        print("\nSTOPPED WITH ERROR:\n" + error)
