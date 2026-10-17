frappe.ui.form.on("Bonus Policy", {
    setup(frm) {
        frm.set_query("expense_account", () => ({
            filters: { company: frm.doc.company, is_group: 0, root_type: "Expense" },
        }));
        frm.set_query("credit_account", () => ({
            filters: { company: frm.doc.company, is_group: 0 },
        }));
    },
});
