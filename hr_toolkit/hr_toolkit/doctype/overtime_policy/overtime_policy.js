const OT_BUTTON_LABELS = {
    "Department": __("Get Departments"),
    "Designation": __("Get Designations"),
    "Employee Grade": __("Get Employee Grades"),
    "Employee": __("Get Employees"),
};

frappe.ui.form.on("Overtime Policy", {
    refresh(frm) {
        frm.add_custom_button(OT_BUTTON_LABELS[frm.doc.applicable_on] || __("Get Items"), () => {
            if (!frm.doc.company) {
                frappe.msgprint(__("Please select Company first."));
                return;
            }
            frm.call("get_all_items").then((r) => {
                frm.refresh_field("items");
                frm.dirty();
                frappe.show_alert({ message: __("{0} rows added", [r.message || 0]), indicator: "green" });
            });
        });
    },

    applicable_on(frm) {
        if ((frm.doc.items || []).length) {
            frm.clear_table("items");
            frm.refresh_field("items");
            frappe.show_alert({ message: __("Items cleared because Applicable On was changed"), indicator: "orange" });
        }
        frm.refresh();
    },
});

frappe.ui.form.on("Overtime Policy Item", {
    items_add(frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "reference_doctype", frm.doc.applicable_on);
    },
});
