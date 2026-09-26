// Copyright (c) 2026, Nexolite and contributors
// For license information, please see license.txt

const BIOMETRIC_API = "hr_toolkit.biometric_sync";

frappe.ui.form.on("Biometric Device", {
	refresh(frm) {
		render_push_help(frm);
		if (frm.is_new()) return;

		const has_ip = !!frm.doc.ip_address;
		const is_pull = frm.doc.connection_mode === "Pull (TCP/IP)";
		const is_live = is_pull && frm.doc.real_time_capture;

		if (is_live) {
			if (frm.doc.enabled) {
				frm.add_custom_button(__("Restart Live Capture"), () => sync_now(frm)).addClass("btn-primary");
			}
		} else {
			if (has_ip) {
				frm.add_custom_button(__("Test Connection"), () => test_connection(frm));
			}
			if (frm.doc.enabled && has_ip) {
				const btn = frm.add_custom_button(is_pull ? __("Sync Now") : __("Pull Missed Punches"), () =>
					sync_now(frm)
				);
				if (is_pull) btn.addClass("btn-primary");
			}
			if (has_ip) {
				frm.add_custom_button(__("Set Device Clock"), () => set_device_clock(frm), __("Actions"));
			}
			if (is_pull) {
				frm.add_custom_button(__("Reset Sync Pointer"), () => reset_sync_pointer(frm), __("Actions"));
			}
		}
		frm.add_custom_button(
			__("View Sync Logs"),
			() => frappe.set_route("List", "Biometric Sync Log", { device: frm.doc.name }),
			__("Actions")
		);

		set_status_indicator(frm);
	},

	connection_mode(frm) {
		render_push_help(frm);
	},
});

function render_push_help(frm) {
	if (frm.doc.connection_mode !== "Push (ADMS)") return;
	const host = window.location.hostname;
	const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
	frm.get_field("push_setup_help").$wrapper.html(`
		<div class="text-muted small" style="line-height:1.7">
			<b>${__("Device setup (Menu > COMM. > Cloud Server Setting / ADMS)")}</b><br>
			${__("Server Address")}: <code>${__("IP address of the ERPNext server")}</code>
			${/^\d+\.\d+\.\d+\.\d+$/.test(host) ? `(<code>${host}</code>)` : ""}<br>
			${__("Server Port")}: <code>${port}</code><br>
			${__("Enable Domain Name")}: <code>${__("Off")}</code> &nbsp; ${__("Enable Proxy Server")}: <code>${__("Off")}</code><br>
			${__("Punches arrive within a few seconds. Last Heartbeat updates about every 10 seconds while the device is online.")}
		</div>`);
}




function set_status_indicator(frm) {
	const colors = { Success: "green", Partial: "orange", Failed: "red" };
	if (frm.doc.real_time_capture && frm.doc.connection_mode !== "Push (ADMS)") {
		const fresh = frm.doc.live_last_seen && moment().diff(moment(frm.doc.live_last_seen), "seconds") < 180;
		const live = fresh && frm.doc.live_status === "Connected";
		let label = live ? __("Live capture running") : __("Live capture not running");
		if (!live && frm.doc.live_status && fresh) label = __("Live capture: {0}", [__(frm.doc.live_status)]);
		frm.dashboard.set_headline_alert(
			`<span class="indicator ${live ? "green" : "red"}">${label}
				${frm.doc.live_last_seen ? " (" + __("last seen") + " " + frappe.datetime.comment_when(frm.doc.live_last_seen) + ")" : ""}
			</span>`
		);
		return;
	}
	if (frm.doc.connection_mode === "Push (ADMS)") {
		const online =
			frm.doc.last_heartbeat &&
			moment().diff(moment(frm.doc.last_heartbeat), "seconds") < 120;
		frm.dashboard.set_headline_alert(
			`<span class="indicator ${online ? "green" : "red"}">
				${online ? __("Device online") : __("Device offline")}
				${frm.doc.last_heartbeat ? " (" + __("last heartbeat") + " " + frappe.datetime.comment_when(frm.doc.last_heartbeat) + ")" : " (" + __("never connected") + ")"}
			</span>`
		);
		return;
	}
	if (frm.doc.last_sync_status) {
		frm.dashboard.set_headline_alert(
			`<span class="indicator ${colors[frm.doc.last_sync_status] || "gray"}">
				${__("Last sync")}: ${__(frm.doc.last_sync_status)}
				${frm.doc.last_synced_on ? " (" + frappe.datetime.comment_when(frm.doc.last_synced_on) + ")" : ""}
			</span>`
		);
	}
}

function test_connection(frm) {
	frappe.call({
		method: `${BIOMETRIC_API}.test_connection`,
		args: { device_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Connecting to {0}...", [frm.doc.ip_address]),
		callback(r) {
			if (!r.message) return;
			const d = r.message;
			let clock_note = "";
			if (d.clock_difference_seconds !== null && d.clock_difference_seconds !== undefined) {
				const diff = Math.abs(d.clock_difference_seconds);
				clock_note =
					diff > 60
						? `<span class="text-danger">${__("Device clock is off by {0} seconds. Use Actions > Set Device Clock.", [diff])}</span>`
						: `<span class="text-success">${__("Device clock is in sync.")}</span>`;
			}
			const row = (label, value) =>
				`<tr><td class="text-muted">${label}</td><td><b>${value ?? "-"}</b></td></tr>`;
			frappe.msgprint({
				title: __("Connected Successfully"),
				indicator: "green",
				message: `
					<table class="table table-sm table-bordered">
						${row(__("Model"), d.device_model_name)}
						${row(__("Serial Number"), d.serial_number)}
						${row(__("Firmware"), d.firmware_version)}
						${row(__("Platform"), d.platform)}
						${row(__("Users on Device"), d.user_count)}
						${row(__("Punch Records on Device"), d.record_count)}
						${row(__("Device Clock"), d.device_time)}
						${row(__("Server Clock"), d.server_time)}
					</table>
					${clock_note}`,
			});
			frm.reload_doc();
		},
	});
}

function sync_now(frm) {
	frappe.call({
		method: `${BIOMETRIC_API}.sync_now`,
		args: { device_name: frm.doc.name },
		freeze: true,
		callback(r) {
			if (r.message === "live") {
				frappe.show_alert({
					message: __("Live capture will reconnect and import missed punches within a minute."),
					indicator: "blue",
				});
				return;
			}
			frappe.show_alert({
				message: __("Sync started in the background. The status will update when it finishes."),
				indicator: "blue",
			});
			poll_until_synced(frm, frm.doc.last_synced_on);
		},
	});
}

function poll_until_synced(frm, previous_sync_time, attempt = 0) {
	if (attempt > 40) return; // stop after about 2 minutes
	setTimeout(() => {
		frappe.db.get_value("Biometric Device", frm.doc.name, "last_synced_on").then((r) => {
			const current = r.message && r.message.last_synced_on;
			if (current && current !== previous_sync_time) {
				frm.reload_doc();
				frappe.show_alert({ message: __("Sync finished."), indicator: "green" });
			} else {
				poll_until_synced(frm, previous_sync_time, attempt + 1);
			}
		});
	}, 3000);
}

function set_device_clock(frm) {
	frappe.confirm(__("Set the clock on {0} to the current server time?", [frm.doc.name]), () => {
		frappe.call({
			method: `${BIOMETRIC_API}.sync_device_clock`,
			args: { device_name: frm.doc.name },
			freeze: true,
			callback(r) {
				frappe.show_alert({
					message: __("Device clock set to {0}", [r.message]),
					indicator: "green",
				});
				frm.reload_doc();
			},
		});
	});
}

function reset_sync_pointer(frm) {
	frappe.confirm(
		__(
			"The next sync will re-read all punches on the device (from 'Import Punches From' if set). Already imported punches will be skipped. Continue?"
		),
		() => {
			frappe.call({
				method: `${BIOMETRIC_API}.reset_sync_pointer`,
				args: { device_name: frm.doc.name },
				callback() {
					frappe.show_alert({ message: __("Sync pointer reset."), indicator: "green" });
					frm.reload_doc();
				},
			});
		}
	);
}
