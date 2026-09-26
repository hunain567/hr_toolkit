# Copyright (c) 2026, Nexolite and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

MIN_INTERVAL_MINUTES = 5


class BiometricSettings(Document):
	def validate(self):
		if cint(self.sync_interval_minutes) < MIN_INTERVAL_MINUTES:
			frappe.msgprint(
				_("Sync interval set to the minimum of {0} minutes.").format(MIN_INTERVAL_MINUTES),
				alert=True,
			)
			self.sync_interval_minutes = MIN_INTERVAL_MINUTES
		if cint(self.keep_logs_for_days) < 1:
			self.keep_logs_for_days = 30
