import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, getdate

COPY_FIELDS = ("income_tax_slab", "payroll_payable_account", "currency")


@frappe.whitelist()
def get_current_salary(employee, effective_date=None):
    """Latest submitted Salary Structure Assignment on or before the effective date."""
    filters = {"employee": employee, "docstatus": 1}
    if effective_date:
        filters["from_date"] = ["<=", effective_date]
    current = frappe.db.get_value(
        "Salary Structure Assignment", filters,
        ["name", "base", "salary_structure", "from_date"],
        as_dict=True, order_by="from_date desc, creation desc",
    )
    return current or {}


class SalaryRevision(Document):
    def validate(self):
        seen = set()
        for row in self.employees:
            if row.employee in seen:
                frappe.throw(_("Row #{0}: Employee {1} is added more than once.").format(row.idx, row.employee))
            seen.add(row.employee)
            self.set_current_salary(row)
            self.validate_row(row)
            self.set_increment(row)
        self.set_totals()

    def on_submit(self):
        for row in self.employees:
            self.make_assignment(row)

    def on_cancel(self):
        for row in reversed(self.employees):
            if row.salary_structure_assignment:
                ssa = frappe.get_doc("Salary Structure Assignment", row.salary_structure_assignment)
                if ssa.docstatus == 1:
                    ssa.cancel()

    def set_current_salary(self, row):
        current = frappe._dict(get_current_salary(row.employee, self.effective_date))
        row.current_salary = flt(current.base)
        row.current_assignment = current.name
        if not row.salary_structure:
            row.salary_structure = current.salary_structure

    @staticmethod
    def set_increment(row):
        row.increment_amount = flt(row.new_salary) - flt(row.current_salary)
        row.increment_percent = (
            flt(row.increment_amount / flt(row.current_salary) * 100, 2) if flt(row.current_salary) else 0
        )

    def validate_row(self, row):
        prefix = _("Row #{0} ({1}): ").format(row.idx, row.employee)
        emp = frappe.db.get_value("Employee", row.employee, ["company", "date_of_joining"], as_dict=True)
        if emp.company != self.company:
            frappe.throw(prefix + _("Employee does not belong to {0}.").format(self.company))
        if not row.salary_structure:
            frappe.throw(prefix + _("Salary Structure is required."))
        if flt(row.new_salary) <= 0:
            frappe.throw(prefix + _("New Salary must be greater than 0."))
        if flt(row.new_salary) == flt(row.current_salary):
            frappe.throw(prefix + _("New Salary is the same as the Current Salary."))
        if emp.date_of_joining and getdate(self.effective_date) < getdate(emp.date_of_joining):
            frappe.throw(prefix + _("Effective Date is before the Date of Joining ({0}).").format(formatdate(emp.date_of_joining)))

        later = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": row.employee, "docstatus": 1, "from_date": [">=", self.effective_date]},
            ["name", "from_date"], as_dict=True,
        )
        if later:
            frappe.throw(prefix + _("Salary Structure Assignment {0} from {1} already exists on or after the Effective Date.").format(
                frappe.bold(later.name), formatdate(later.from_date)
            ))

        slip = frappe.db.get_value(
            "Salary Slip",
            {"employee": row.employee, "docstatus": 1, "end_date": [">=", self.effective_date]},
            ["name", "start_date", "end_date"], as_dict=True,
        )
        if slip:
            frappe.throw(prefix + _("Salary Slip {0} ({1} to {2}) is already submitted after the Effective Date.").format(
                frappe.bold(slip.name), formatdate(slip.start_date), formatdate(slip.end_date)
            ))

    def set_totals(self):
        self.total_employees = len(self.employees)
        self.total_current_salary = flt(sum(flt(r.current_salary) for r in self.employees), 2)
        self.total_new_salary = flt(sum(flt(r.new_salary) for r in self.employees), 2)
        self.total_increment = flt(self.total_new_salary - self.total_current_salary, 2)

    def make_assignment(self, row):
        ssa = frappe.get_doc({
            "doctype": "Salary Structure Assignment",
            "employee": row.employee,
            "company": self.company,
            "salary_structure": row.salary_structure,
            "from_date": self.effective_date,
            "base": row.new_salary,
        })
        if row.current_assignment:
            current = frappe.get_doc("Salary Structure Assignment", row.current_assignment)
            for field in COPY_FIELDS:
                if current.get(field) and not ssa.get(field):
                    ssa.set(field, current.get(field))
        ssa.flags.ignore_permissions = True
        ssa.insert()
        ssa.submit()
        row.db_set("salary_structure_assignment", ssa.name)

    def get_increment(self, current):
        if not flt(self.increment_value):
            return 0
        if self.increment_type == "Amount":
            return flt(self.increment_value)
        return round(flt(current) * flt(self.increment_value) / 100)

    @frappe.whitelist()
    def get_employees(self):
        """Fill Employees with all active employees (filters applied) and their current salary."""
        if not (self.company and self.effective_date):
            frappe.throw(_("Please select Company and Effective Date first."))

        filters = {"company": self.company, "status": "Active", "date_of_joining": ["<=", self.effective_date]}
        if self.department:
            filters["department"] = self.department
        if self.designation:
            filters["designation"] = self.designation
        employees = frappe.get_all(
            "Employee", filters=filters,
            fields=["name", "employee_name", "department", "designation"], order_by="name",
        )

        self.set("employees", [])
        skipped = 0
        for e in employees:
            current = frappe._dict(get_current_salary(e.name, self.effective_date))
            if not current.name:
                skipped += 1
                continue
            new_salary = flt(current.base) + self.get_increment(current.base)
            row = self.append("employees", {
                "employee": e.name,
                "employee_name": e.employee_name,
                "department": e.department,
                "designation": e.designation,
                "salary_structure": current.salary_structure,
                "current_salary": flt(current.base),
                "current_assignment": current.name,
                "new_salary": new_salary,
            })
            self.set_increment(row)
        self.set_totals()
        return {"added": len(self.employees), "skipped": skipped}

    @frappe.whitelist()
    def apply_increment(self):
        """Apply the default increment to every row."""
        for row in self.employees:
            row.new_salary = flt(row.current_salary) + self.get_increment(row.current_salary)
            self.set_increment(row)
        self.set_totals()
