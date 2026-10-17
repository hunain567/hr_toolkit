const CHECKIN_TOOL = "hr_toolkit.hr_toolkit.doctype.checkin_adjustment_tool.checkin_adjustment_tool";

frappe.ui.form.on("Checkin Adjustment Tool", {
    onload(frm) {
        if (!frm.doc.from_date) {
            frm.set_value("from_date", frappe.datetime.month_start());
        }
        if (!frm.doc.to_date) {
            frm.set_value("to_date", frappe.datetime.get_today());
        }
    },

    refresh(frm) {
        frm.disable_save();
        highlight_days(frm);
        frm.get_field("days").grid.cannot_add_rows = true;
        frm.add_custom_button(__("Reload"), () => load_checkins(frm));
        frm.add_custom_button(__("Save Checkins"), () => save_checkins(frm)).addClass("btn-primary");
    },

    employee(frm) {
        load_checkins(frm);
    },
    from_date(frm) {
        load_checkins(frm);
    },
    to_date(frm) {
        load_checkins(frm);
    },
});

function load_checkins(frm) {
    if (!frm.doc.employee || !frm.doc.from_date || !frm.doc.to_date) {
        return;
    }
    frappe.call({
        method: `${CHECKIN_TOOL}.get_month_checkins`,
        args: { employee: frm.doc.employee, from_date: frm.doc.from_date, to_date: frm.doc.to_date },
        freeze: true,
        freeze_message: __("Loading checkins..."),
        callback(r) {
            frm.clear_table("days");
            (r.message || []).forEach((d) => frm.add_child("days", d));
            frm.refresh_field("days");
            highlight_days(frm);
            frm.doc.__unsaved = 0;
        },
    });
}

function save_checkins(frm) {
    const changed = (frm.doc.days || []).filter(
        (r) => (r.in_time || "") !== (r.original_in || "") || (r.out_time || "") !== (r.original_out || "")
    );
    if (!changed.length) {
        frappe.msgprint(__("No changes to save."));
        return;
    }
    const deletes = changed.filter(
        (r) => (r.in_checkin && !r.in_time) || (r.out_checkin && !r.out_time)
    ).length;
    let msg = __("Save checkins for {0} days?", [changed.length]);
    if (deletes) {
        msg += "<br>" + __("{0} checkins will be deleted because their time was cleared.", [deletes]);
    }
    frappe.confirm(msg, () => {
        frappe.call({
            method: `${CHECKIN_TOOL}.save_month_checkins`,
            args: { employee: frm.doc.employee, rows: changed, mark_attendance: frm.doc.mark_attendance },
            freeze: true,
            freeze_message: __("Saving checkins..."),
            callback(r) {
                const res = r.message || {};
                let text = __("{0} created, {1} updated, {2} deleted, {3} attendance updated", [
                    res.created || 0, res.updated || 0, res.deleted || 0, res.attendance || 0,
                ]);
                if ((res.errors || []).length) {
                    text += "<br><br><b>" + __("Errors") + "</b><br>" + res.errors.join("<br>");
                }
                frappe.msgprint({
                    title: __("Checkin Adjustment"),
                    message: text,
                    indicator: (res.errors || []).length ? "orange" : "green",
                });
                load_checkins(frm);
            },
        });
    });
}

frappe.ui.form.on("Checkin Adjustment Detail", {
    in_time(frm, cdt, cdn) {
        format_hm(cdt, cdn, "in_time", "original_in");
    },
    out_time(frm, cdt, cdn) {
        format_hm(cdt, cdn, "out_time", "original_out");
    },
});

function format_hm(cdt, cdn, field, original_field) {
    const row = locals[cdt][cdn];
    const value = (row[field] || "").trim();
    if (!value) {
        return;
    }
    let text = value.replace(".", ":");
    if (/^\d+$/.test(text)) {
        text = text.length <= 2 ? `${text}:00` : `${text.slice(0, -2)}:${text.slice(-2)}`;
    }
    const m = text.match(/^(\d{1,2}):(\d{2})(:\d{2})?$/);
    if (!m || +m[1] > 23 || +m[2] > 59) {
        frappe.show_alert({ message: __("Invalid time {0}. Use HH:MM, for example 08:30", [value]), indicator: "red" });
        frappe.model.set_value(cdt, cdn, field, row[original_field] || "");
        return;
    }
    const formatted = `${m[1].padStart(2, "0")}:${m[2]}`;
    if (formatted !== value) {
        frappe.model.set_value(cdt, cdn, field, formatted);
    }
}

function highlight_days(frm) {
    // Weekly off rows in light yellow, holidays in light blue
    setTimeout(() => {
        const grid = frm.get_field("days").grid;
        (grid.grid_rows || []).forEach((row) => {
            const remarks = row.doc.remarks || "";
            let color = "";
            if (remarks.includes("Missing IN") || remarks.includes("Missing OUT")) {
                color = "rgba(220, 53, 69, 0.15)";
            } else if (remarks.includes("Weekly Off")) {
                color = "rgba(255, 193, 7, 0.20)";
            } else if (remarks.includes("Holiday")) {
                color = "rgba(23, 162, 184, 0.15)";
            }
            $(row.wrapper).find(".data-row").css("background-color", color);
            $(row.wrapper).find('[data-fieldname="day"]').css("font-weight", color ? "700" : "");
        });
    }, 100);
}
