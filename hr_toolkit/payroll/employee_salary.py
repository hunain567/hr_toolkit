import frappe
from frappe.utils import flt, getdate, today


def get_current_salary(employee, on_date=None):
    """Base from the latest submitted Salary Structure Assignment on or before on_date."""
    return flt(frappe.db.get_value(
        "Salary Structure Assignment",
        {"employee": employee, "docstatus": 1, "from_date": ["<=", getdate(on_date or today())]},
        "base",
        order_by="from_date desc, creation desc",
    ))


def update_employee_salary(doc, method=None):
    """Salary Structure Assignment on_submit / on_cancel: refresh Salary on the Employee."""
    frappe.db.set_value(
        "Employee", doc.employee, "hrt_salary", get_current_salary(doc.employee), update_modified=False
    )


def update_all():
    """Daily: refresh Salary on every Employee (increments become visible on their from date)."""
    rows = frappe.db.sql(
        """select ssa.employee, ssa.base
           from `tabSalary Structure Assignment` ssa
           inner join (
               select employee, max(from_date) as from_date
               from `tabSalary Structure Assignment`
               where docstatus = 1 and from_date <= %s
               group by employee
           ) latest on latest.employee = ssa.employee and latest.from_date = ssa.from_date
           where ssa.docstatus = 1""",
        (today(),),
        as_dict=True,
    )
    salaries = {r.employee: flt(r.base) for r in rows}
    for name, current in frappe.get_all("Employee", fields=["name", "hrt_salary"], as_list=True):
        new = salaries.get(name, 0)
        if flt(current) != new:
            frappe.db.set_value("Employee", name, "hrt_salary", new, update_modified=False)
    frappe.db.commit()
