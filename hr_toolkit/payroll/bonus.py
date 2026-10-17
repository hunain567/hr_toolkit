import frappe
from dateutil.relativedelta import relativedelta
from frappe.utils import cint, flt, formatdate, getdate

from hr_toolkit.payroll.salary_slip import get_base_salary


def completed_months(joining, on_date):
    """Full months of service from joining date to on_date (10-Apr to 09-Oct = 5, to 10-Oct = 6)."""
    if not joining or getdate(joining) > getdate(on_date):
        return 0
    diff = relativedelta(getdate(on_date), getdate(joining))
    return diff.years * 12 + diff.months


def get_bonus_row(employee, bonus_date, policy, precision=0):
    """Bonus details for one employee as per Bonus Policy."""
    emp = frappe.db.get_value(
        "Employee", employee,
        ["employee_name", "department", "date_of_joining", "relieving_date"],
        as_dict=True,
    )
    months = completed_months(emp.date_of_joining, bonus_date)
    base = get_base_salary(employee, None, bonus_date)
    calculated = flt(base * flt(policy.bonus_percent) / 100, precision)

    if emp.relieving_date and getdate(emp.relieving_date) < getdate(bonus_date):
        eligible, reason = False, f"Not eligible (left on {formatdate(emp.relieving_date)})"
    elif months < cint(policy.min_service_months):
        eligible, reason = False, f"Not eligible ({months} months service, minimum {cint(policy.min_service_months)})"
    elif not base:
        eligible, reason = False, "Not eligible (no Salary Structure Assignment)"
    else:
        eligible, reason = True, "Eligible"

    return frappe._dict(
        employee=employee,
        employee_name=emp.employee_name,
        department=emp.department,
        date_of_joining=emp.date_of_joining,
        service_months=months,
        monthly_salary=base,
        bonus_percent=flt(policy.bonus_percent),
        calculated_amount=calculated if eligible else 0,
        eligible=eligible,
        eligibility=reason,
    )
