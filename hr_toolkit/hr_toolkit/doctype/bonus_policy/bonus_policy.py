import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class BonusPolicy(Document):
    def validate(self):
        if cint(self.min_service_months) < 0:
            frappe.throw(_("Minimum Service (Months) cannot be negative."))
        if flt(self.bonus_percent) <= 0:
            frappe.throw(_("Bonus % of Monthly Salary must be greater than 0."))
        for field in ("expense_account", "credit_account"):
            account = self.get(field)
            if account and frappe.db.get_value("Account", account, "company") != self.company:
                frappe.throw(_("{0} {1} does not belong to {2}.").format(self.meta.get_label(field), account, self.company))
