import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class HRToolkitSettings(Document):
    def validate(self):
        if cint(self.working_days) <= 0:
            frappe.throw("Working Days 0 se zyada honi chahiye.")
        if self.count_half_day and flt(self.half_day_value) <= 0:
            frappe.throw("Half Day ki value 0 se zyada honi chahiye.")
