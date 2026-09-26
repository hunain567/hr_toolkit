# Copyright (c) 2026, Nexolite and contributors
# For license information, please see license.txt

import ipaddress

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

PULL_MODE = "Pull (TCP/IP)"
PUSH_MODE = "Push (ADMS)"

# Changing any of these on an enabled device triggers an immediate sync / reconnect
CONNECTION_FIELDS = ("ip_address", "port", "comm_password", "force_udp", "connection_mode", "real_time_capture")


class BiometricDevice(Document):
	@property
	def mode(self):
		# Older installs have no connection_mode field; they are pull devices.
		return self.get("connection_mode") or PULL_MODE

	def validate(self):
		self.ip_address = (self.ip_address or "").strip()
		if self.meta.has_field("serial_number"):
			self.serial_number = (self.serial_number or "").strip() or None

		if self.mode == PULL_MODE and not self.ip_address:
			frappe.throw(_("IP Address is required for Pull (TCP/IP) mode."))
		if self.mode == PUSH_MODE and not self.get("serial_number"):
			frappe.throw(_("Serial Number is required for Push (ADMS) mode."))
		if self.mode == PUSH_MODE:
			self.real_time_capture = 0

		if self.ip_address:
			self.validate_ip_address()
		if self.mode == PULL_MODE:
			self.validate_port()
			self.validate_unique_ip()
		if cint(self.timeout) <= 0:
			self.timeout = 30
		if not cint(self.port):
			self.port = 4370

	def after_insert(self):
		self.queue_first_sync()

	def on_update(self):
		if self.flags.in_insert:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		just_enabled = cint(self.enabled) and not cint(before.enabled)
		connection_changed = any(self.get(f) != before.get(f) for f in CONNECTION_FIELDS)
		if just_enabled or connection_changed:
			self.queue_first_sync()

	def queue_first_sync(self):
		"""Pull punches right away instead of waiting for the scheduler."""
		if not cint(self.enabled) or self.mode != PULL_MODE or not self.ip_address:
			return

		if cint(self.get("real_time_capture")):
			# The live listener picks the device up within 30 seconds and
			# imports missed punches itself; ask it to reconnect if running.
			self.db_set("live_restart_requested", 1, update_modified=False)
			frappe.msgprint(
				_("Live capture for {0} will start within 30 seconds.").format(self.name),
				alert=True,
				indicator="blue",
			)
			return

		from hr_toolkit.biometric_sync import enqueue_sync

		enqueue_sync(self.name, "Manual")
		frappe.msgprint(
			_("First sync for {0} has started in the background.").format(self.name),
			alert=True,
			indicator="blue",
		)

	def validate_ip_address(self):
		try:
			ipaddress.ip_address(self.ip_address)
		except ValueError:
			frappe.throw(_("{0} is not a valid IP address.").format(frappe.bold(self.ip_address)))

	def validate_port(self):
		if not 1 <= cint(self.port) <= 65535:
			frappe.throw(_("Port must be between 1 and 65535."))

	def validate_unique_ip(self):
		filters = {
			"ip_address": self.ip_address,
			"port": cint(self.port),
			"name": ["!=", self.name],
		}
		if self.meta.has_field("connection_mode"):
			filters["connection_mode"] = PULL_MODE
		duplicate = frappe.db.get_value("Biometric Device", filters, "name")
		if duplicate:
			frappe.throw(
				_("Device {0} already uses {1}:{2}.").format(frappe.bold(duplicate), self.ip_address, self.port)
			)
