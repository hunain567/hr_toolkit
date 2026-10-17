import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class HRToolkitSettings(Document):
    def validate(self):
        if not self.calculation_method:
            frappe.throw(_("Calculation Method is required."))
        if cint(self.rounding_precision) < 0 or cint(self.rounding_precision) > 2:
            frappe.throw(_("Salary Rounding Precision must be between 0 and 2."))
        if self.count_half_day and not (0 < flt(self.half_day_value) <= 1):
            frappe.throw(_("Half Day Value must be greater than 0 and not more than 1."))
