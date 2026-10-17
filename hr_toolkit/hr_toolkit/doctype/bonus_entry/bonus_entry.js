frappe.ui.form.on("Bonus Entry", {
    setup(frm) {
        frm.set_query("bonus_policy", () => ({ filters: { company: frm.doc.company, enabled: 1 } }));
        frm.set_query("expense_account", () => ({
            filters: { company: frm.doc.company, is_group: 0, root_type: "Expense" },
        }));
        frm.set_query("credit_account", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Get Employees"), () => {
                if (!frm.doc.company || !frm.doc.bonus_date || !frm.doc.bonus_policy) {
                    frappe.msgprint(__("Please select Company, Bonus Date and Bonus Policy first."));
                    return;
                }
                frm.call("get_employees").then((r) => {
                    frm.refresh_fields();
                    frm.dirty();
                    const res = r.message || {};
                    frappe.show_alert({
                        message: __("{0} employees added, {1} not eligible", [res.added || 0, res.skipped || 0]),
                        indicator: res.added ? "green" : "orange",
                    });
                });
            });
        }
        if (frm.doc.journal_entry) {
            frm.add_custom_button(__("Journal Entry"), () => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry), __("View"));
        }
    },
});

frappe.ui.form.on("Bonus Entry Detail", {
    bonus_amount(frm) {
        set_bonus_totals(frm);
    },
    employees_remove(frm) {
        set_bonus_totals(frm);
    },
});

function set_bonus_totals(frm) {
    let count = 0;
    let amount = 0;
    (frm.doc.employees || []).forEach((row) => {
        if (flt(row.bonus_amount) > 0) {
            count += 1;
            amount += flt(row.bonus_amount);
        }
    });
    frm.set_value("total_employees", count);
    frm.set_value("total_bonus_amount", flt(amount, 2));
}
