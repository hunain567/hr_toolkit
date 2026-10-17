import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

ITEM_FILTERS = {
    "Department": lambda company: {"company": company, "is_group": 0},
    "Designation": lambda company: {},
    "Employee Grade": lambda company: {},
    "Employee": lambda company: {"company": company, "status": "Active"},
}


class OvertimePolicy(Document):
    def validate(self):
        self.validate_items()
        self.validate_values()
        self.validate_duplicate_policy()

    def validate_items(self):
        seen = set()
        for row in self.items:
            row.reference_doctype = self.applicable_on
            if row.reference_name in seen:
                frappe.throw(
                    _("Row #{0}: {1} {2} is added more than once.").format(
                        row.idx, self.applicable_on, row.reference_name
                    )
                )
            seen.add(row.reference_name)

    def validate_values(self):
        if flt(self.rate_multiplier) <= 0:
            frappe.throw(_("Rate Multiplier must be greater than 0."))
        if flt(self.min_salary) < 0 or flt(self.max_salary) < 0:
            frappe.throw(_("Minimum and Maximum Monthly Salary cannot be negative."))
        if flt(self.max_salary) and flt(self.min_salary) > flt(self.max_salary):
            frappe.throw(_("Minimum Monthly Salary cannot be greater than Maximum Monthly Salary."))

    def validate_duplicate_policy(self):
        if not self.enabled:
            return
        other = frappe.db.get_value(
            "Overtime Policy",
            {"company": self.company, "day_type": self.day_type, "enabled": 1, "name": ["!=", self.name]},
            "name",
        )
        if other:
            frappe.throw(
                _("Overtime Policy {0} is already enabled for {1} with Day Type {2}.").format(
                    frappe.bold(other), self.company, self.day_type
                )
            )

    @frappe.whitelist()
    def get_all_items(self):
        """Add all records of the selected Applicable On (e.g. all Departments of the company)."""
        if not self.company:
            frappe.throw(_("Please select Company first."))
        filters = ITEM_FILTERS[self.applicable_on](self.company)
        names = frappe.get_all(self.applicable_on, filters=filters, pluck="name", order_by="name")
        existing = {row.reference_name for row in self.items}
        added = 0
        for name in names:
            if name not in existing:
                self.append("items", {"reference_doctype": self.applicable_on, "reference_name": name})
                added += 1
        return added
