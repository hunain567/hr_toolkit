import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class HRToolkitSettings(Document):
    def validate(self):
        if cint(self.working_days) <= 0:
            frappe.throw(_("Working Days per Month must be greater than 0."))
        if self.count_half_day and flt(self.half_day_value) <= 0:
            frappe.throw(_("Half Day Value must be greater than 0."))
