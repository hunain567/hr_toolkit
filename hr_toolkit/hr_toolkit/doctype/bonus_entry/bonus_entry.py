import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate

from hr_toolkit.payroll.bonus import get_bonus_row
from hr_toolkit.payroll.salary_slip import get_settings


class BonusEntry(Document):
    def validate(self):
        self.validate_policy()
        self.validate_rows()
        self.validate_duplicate_entries()
        self.set_totals()

    def on_submit(self):
        self.make_journal_entry()

    def on_cancel(self):
        if self.journal_entry:
            je = frappe.get_doc("Journal Entry", self.journal_entry)
            if je.docstatus == 1:
                je.cancel()

    def get_policy(self):
        return frappe.get_cached_doc("Bonus Policy", self.bonus_policy)

    def validate_policy(self):
        policy = self.get_policy()
        if policy.company != self.company:
            frappe.throw(_("Bonus Policy {0} belongs to {1}.").format(self.bonus_policy, policy.company))
        if not policy.enabled:
            frappe.throw(_("Bonus Policy {0} is disabled.").format(self.bonus_policy))

    def validate_rows(self):
        policy = self.get_policy()
        precision = get_settings().precision
        seen = set()
        for row in self.employees:
            if row.employee in seen:
                frappe.throw(_("Row #{0}: Employee {1} is added more than once.").format(row.idx, row.employee))
            seen.add(row.employee)
            if frappe.db.get_value("Employee", row.employee, "company") != self.company:
                frappe.throw(_("Row #{0}: Employee {1} does not belong to {2}.").format(row.idx, row.employee, self.company))

            data = get_bonus_row(row.employee, self.bonus_date, policy, precision)
            for field in ("employee_name", "department", "date_of_joining", "service_months",
                          "monthly_salary", "bonus_percent", "calculated_amount", "eligibility"):
                row.set(field, data.get(field))

            if flt(row.bonus_amount) < 0:
                frappe.throw(_("Row #{0}: Bonus Amount cannot be negative.").format(row.idx))
            if not data.eligible and flt(row.bonus_amount) > 0:
                frappe.throw(
                    _("Row #{0}: {1} is {2}. Bonus Amount must be 0.").format(row.idx, row.employee, data.eligibility.lower())
                )

    def validate_duplicate_entries(self):
        employees = [row.employee for row in self.employees if flt(row.bonus_amount) > 0]
        if not employees:
            return
        duplicates = frappe.db.sql(
            """select d.employee, e.name from `tabBonus Entry Detail` d
               inner join `tabBonus Entry` e on e.name = d.parent
               where e.docstatus = 1 and e.bonus_date = %s and e.name != %s
                 and d.bonus_amount > 0 and d.employee in %s""",
            (self.bonus_date, self.name or "", tuple(employees)),
            as_dict=True,
        )
        if duplicates:
            lines = "<br>".join(f"{d.employee} ({d.name})" for d in duplicates)
            frappe.throw(
                _("Bonus for these employees on {0} is already submitted:<br>{1}").format(
                    formatdate(self.bonus_date), lines
                ),
                title=_("Duplicate Bonus"),
            )

    def set_totals(self):
        paid = [row for row in self.employees if flt(row.bonus_amount) > 0]
        self.total_employees = len(paid)
        self.total_bonus_amount = flt(sum(flt(row.bonus_amount) for row in paid), 2)

    def make_journal_entry(self):
        if not flt(self.total_bonus_amount):
            return
        cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
        credit_type = frappe.db.get_value("Account", self.credit_account, "account_type")
        remark = _("Bonus Entry {0} ({1}) on {2}").format(self.name, self.bonus_policy, formatdate(self.bonus_date))

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = self.company
        je.posting_date = self.bonus_date
        je.user_remark = remark
        je.append("accounts", {
            "account": self.expense_account,
            "debit_in_account_currency": self.total_bonus_amount,
            "cost_center": cost_center,
        })
        if credit_type == "Payable":
            for row in self.employees:
                if flt(row.bonus_amount) > 0:
                    je.append("accounts", {
                        "account": self.credit_account,
                        "credit_in_account_currency": flt(row.bonus_amount),
                        "party_type": "Employee",
                        "party": row.employee,
                        "cost_center": cost_center,
                    })
        else:
            je.append("accounts", {
                "account": self.credit_account,
                "credit_in_account_currency": self.total_bonus_amount,
                "cost_center": cost_center,
            })
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        self.db_set("journal_entry", je.name)

    @frappe.whitelist()
    def get_employees(self):
        """Fill Employees as per Bonus Policy (eligible only, unless Include Not Eligible Employees is ticked)."""
        if not (self.company and self.bonus_date and self.bonus_policy):
            frappe.throw(_("Please select Company, Bonus Date and Bonus Policy first."))

        policy = self.get_policy()
        precision = get_settings().precision
        filters = {"company": self.company, "status": ["in", ["Active", "Left"]]}
        if self.department:
            filters["department"] = self.department
        employees = frappe.get_all("Employee", filters=filters, pluck="name", order_by="name")

        self.set("employees", [])
        skipped = 0
        for employee in employees:
            data = get_bonus_row(employee, self.bonus_date, policy, precision)
            if not data.eligible and not self.include_not_eligible:
                skipped += 1
                continue
            data.bonus_amount = data.calculated_amount
            data.pop("eligible")
            self.append("employees", data)

        self.set_totals()
        return {"added": len(self.employees), "skipped": skipped}
