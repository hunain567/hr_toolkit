// Copyright (c) 2026, Nexolite and contributors
// For license information, please see license.txt

frappe.ui.form.on("Biometric Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sync All Devices Now"), () => {
			frappe.call({
				method: "hr_toolkit.biometric_sync.sync_all_now",
				freeze: true,
				callback(r) {
					frappe.show_alert({
						message: __("{0} device(s) queued for sync.", [r.message || 0]),
						indicator: "blue",
					});
				},
			});
		});
		frm.add_custom_button(__("Devices"), () => frappe.set_route("List", "Biometric Device"));
		frm.add_custom_button(__("Sync Logs"), () => frappe.set_route("List", "Biometric Sync Log"));
	},
});
