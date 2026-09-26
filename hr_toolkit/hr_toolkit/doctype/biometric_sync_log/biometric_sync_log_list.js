// Copyright (c) 2026, Nexolite and contributors
// For license information, please see license.txt

frappe.listview_settings["Biometric Sync Log"] = {
	get_indicator(doc) {
		const colors = { Success: "green", Partial: "orange", Failed: "red" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
