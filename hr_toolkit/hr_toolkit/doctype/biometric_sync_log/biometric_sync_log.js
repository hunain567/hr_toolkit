// Copyright (c) 2026, Nexolite and contributors
// For license information, please see license.txt

frappe.ui.form.on("Biometric Sync Log", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.device) {
			frm.add_custom_button(__("Open Device"), () =>
				frappe.set_route("Form", "Biometric Device", frm.doc.device)
			);
		}
	},
});
