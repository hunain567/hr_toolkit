frappe.ui.form.on("Overtime Entry", {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Get Employees"), () => {
                if (!frm.doc.company || !frm.doc.overtime_date) {
                    frappe.msgprint(__("Please select Company and Overtime Date first."));
                    return;
                }
                frm.call("get_employees").then((r) => {
                    frm.refresh_fields();
                    frm.dirty();
                    frappe.show_alert({
                        message: __("{0} employees with overtime found", [r.message || 0]),
                        indicator: r.message ? "green" : "orange",
                    });
                });
            });
        }
    },
});

frappe.ui.form.on("Overtime Entry Detail", {
    overtime_hours(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        frappe.model.set_value(
            cdt, cdn, "overtime_amount",
            flt(flt(row.hourly_rate) * flt(row.overtime_hours) * flt(row.rate_multiplier), 2)
        );
        set_totals(frm);
    },
    overtime_amount(frm) {
        set_totals(frm);
    },
    employees_remove(frm) {
        set_totals(frm);
    },
});

function set_totals(frm) {
    let hours = 0;
    let amount = 0;
    (frm.doc.employees || []).forEach((row) => {
        hours += flt(row.overtime_hours);
        amount += flt(row.overtime_amount);
    });
    frm.set_value("total_overtime_hours", flt(hours, 2));
    frm.set_value("total_overtime_amount", flt(amount, 2));
}
