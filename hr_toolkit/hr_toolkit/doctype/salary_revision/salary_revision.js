const SALARY_REVISION = "hr_toolkit.hr_toolkit.doctype.salary_revision.salary_revision";

frappe.ui.form.on("Salary Revision", {
    setup(frm) {
        frm.set_query("department", () => ({ filters: { company: frm.doc.company } }));
        frm.set_query("salary_structure", "employees", () => ({
            filters: { company: frm.doc.company, docstatus: 1, is_active: "Yes" },
        }));
        frm.set_query("employee", "employees", () => ({
            filters: { company: frm.doc.company, status: "Active" },
        }));
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Get Employees"), () => {
                if (!frm.doc.company || !frm.doc.effective_date) {
                    frappe.msgprint(__("Please select Company and Effective Date first."));
                    return;
                }
                frm.call("get_employees").then((r) => {
                    frm.refresh_fields();
                    frm.dirty();
                    const res = r.message || {};
                    frappe.show_alert({
                        message: __("{0} employees added, {1} without salary skipped", [res.added || 0, res.skipped || 0]),
                        indicator: res.added ? "green" : "orange",
                    });
                });
            });
            frm.add_custom_button(__("Apply Increment to All"), () => {
                if (!flt(frm.doc.increment_value)) {
                    frappe.msgprint(__("Please enter Default Increment Value first."));
                    return;
                }
                frm.call("apply_increment").then(() => {
                    frm.refresh_fields();
                    frm.dirty();
                });
            });
        }
    },

    effective_date(frm) {
        (frm.doc.employees || []).forEach((row) => load_current_salary(frm, row.doctype, row.name));
    },
});

frappe.ui.form.on("Salary Revision Detail", {
    employee(frm, cdt, cdn) {
        load_current_salary(frm, cdt, cdn);
    },
    new_salary(frm, cdt, cdn) {
        if (frm._setting) return;
        const row = locals[cdt][cdn];
        const amount = flt(row.new_salary) - flt(row.current_salary);
        set_row(frm, cdt, cdn, {
            increment_amount: amount,
            increment_percent: flt(row.current_salary) ? flt((amount / flt(row.current_salary)) * 100, 2) : 0,
        });
    },
    increment_amount(frm, cdt, cdn) {
        if (frm._setting) return;
        const row = locals[cdt][cdn];
        set_row(frm, cdt, cdn, {
            new_salary: flt(row.current_salary) + flt(row.increment_amount),
            increment_percent: flt(row.current_salary) ? flt((flt(row.increment_amount) / flt(row.current_salary)) * 100, 2) : 0,
        });
    },
    increment_percent(frm, cdt, cdn) {
        if (frm._setting) return;
        const row = locals[cdt][cdn];
        const amount = Math.round((flt(row.current_salary) * flt(row.increment_percent)) / 100);
        set_row(frm, cdt, cdn, { increment_amount: amount, new_salary: flt(row.current_salary) + amount });
    },
    employees_remove(frm) {
        set_totals(frm);
    },
});

function load_current_salary(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.employee || frm.doc.docstatus !== 0) return;
    frappe.call({
        method: `${SALARY_REVISION}.get_current_salary`,
        args: { employee: row.employee, effective_date: frm.doc.effective_date },
        callback(r) {
            const cur = r.message || {};
            const current = flt(cur.base);
            let increment = 0;
            if (flt(frm.doc.increment_value)) {
                increment = frm.doc.increment_type === "Amount"
                    ? flt(frm.doc.increment_value)
                    : Math.round((current * flt(frm.doc.increment_value)) / 100);
            }
            const new_salary = flt(row.new_salary) || current + increment;
            set_row(frm, cdt, cdn, {
                current_salary: current,
                current_assignment: cur.name || "",
                salary_structure: row.salary_structure || cur.salary_structure || "",
                new_salary: new_salary,
                increment_amount: new_salary - current,
                increment_percent: current ? flt(((new_salary - current) / current) * 100, 2) : 0,
            });
        },
    });
}

function set_row(frm, cdt, cdn, values) {
    frm._setting = true;
    const promises = Object.keys(values).map((k) => frappe.model.set_value(cdt, cdn, k, values[k]));
    Promise.all(promises).then(() => {
        frm._setting = false;
        set_totals(frm);
    });
}

function set_totals(frm) {
    let current = 0;
    let next = 0;
    (frm.doc.employees || []).forEach((r) => {
        current += flt(r.current_salary);
        next += flt(r.new_salary);
    });
    frm.set_value({
        total_employees: (frm.doc.employees || []).length,
        total_current_salary: current,
        total_new_salary: next,
        total_increment: next - current,
    });
}
