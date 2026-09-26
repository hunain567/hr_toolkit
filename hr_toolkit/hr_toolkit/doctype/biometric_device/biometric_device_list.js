// Copyright (c) 2026, Nexolite and contributors
// For license information, please see license.txt

frappe.listview_settings["Biometric Device"] = {
	add_fields: ["enabled", "last_sync_status", "connection_mode", "last_heartbeat", "real_time_capture", "live_status", "live_last_seen"],
	get_indicator(doc) {
		if (!doc.enabled) return [__("Disabled"), "gray", "enabled,=,0"];
		if (doc.real_time_capture && doc.connection_mode !== "Push (ADMS)") {
			const fresh = doc.live_last_seen && moment().diff(moment(doc.live_last_seen), "seconds") < 180;
			return fresh && doc.live_status === "Connected"
				? [__("Live"), "green", "real_time_capture,=,1"]
				: [__("Live Offline"), "red", "real_time_capture,=,1"];
		}
		if (doc.connection_mode === "Push (ADMS)") {
			const online = doc.last_heartbeat && moment().diff(moment(doc.last_heartbeat), "seconds") < 120;
			return online
				? [__("Online"), "green", "connection_mode,=,Push (ADMS)"]
				: [__("Offline"), "red", "connection_mode,=,Push (ADMS)"];
		}
		const colors = { Success: "green", Partial: "orange", Failed: "red" };
		if (doc.last_sync_status) {
			return [__(doc.last_sync_status), colors[doc.last_sync_status], `last_sync_status,=,${doc.last_sync_status}`];
		}
		return [__("Not Synced"), "blue", "enabled,=,1"];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Sync All Devices Now"), () => {
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
	},
};
