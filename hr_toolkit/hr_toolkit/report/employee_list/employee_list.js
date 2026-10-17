frappe.query_reports["Employee List"] = {
    tree: true,
    initial_depth: 1,

    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: "\nActive\nInactive\nSuspended\nLeft",
            default: "Active",
        },
        {
            fieldname: "department",
            label: __("Department"),
            fieldtype: "Link",
            options: "Department",
            get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
        },
        { fieldname: "designation", label: __("Designation"), fieldtype: "Link", options: "Designation" },
        { fieldname: "employment_type", label: __("Employment Type"), fieldtype: "Link", options: "Employment Type" },
        { fieldname: "gender", label: __("Gender"), fieldtype: "Link", options: "Gender" },
        {
            fieldname: "blood_group",
            label: __("Blood Group"),
            fieldtype: "Select",
            options: "\nA+\nA-\nB+\nB-\nAB+\nAB-\nO+\nO-",
        },
        { fieldname: "joining_from", label: __("Joining From"), fieldtype: "Date" },
        { fieldname: "joining_to", label: __("Joining To"), fieldtype: "Date" },
        { fieldname: "salary_from", label: __("Salary From"), fieldtype: "Currency" },
        { fieldname: "salary_to", label: __("Salary To"), fieldtype: "Currency" },
        {
            fieldname: "group_by",
            label: __("Group By"),
            fieldtype: "Select",
            options: "\nDepartment\nDesignation\nEmployment Type\nGender\nStatus",
        },
        { fieldname: "only_missing", label: __("Only Missing Information"), fieldtype: "Check" },
    ],

    formatter(value, row, column, data, default_formatter) {
        const left = (html) => String(html || "").replace(/text-align:\s*right/g, "text-align: left");

        if (!data) {
            return left(default_formatter(value, row, column, data));
        }
        if (data.is_group) {
            return `<b>${left(default_formatter(value, row, column, data))}</b>`;
        }
        // Employee ID only (no employee name next to it), still clickable
        if (column.fieldname === "employee" && data.employee) {
            return `<a href="/app/employee/${encodeURIComponent(data.employee)}">${data.employee}</a>`;
        }
        if (column.fieldname === "status" && data.status) {
            const colors = { Active: "green", Left: "red", Inactive: "orange", Suspended: "orange" };
            return `<span class="indicator-pill ${colors[data.status] || "gray"}">${__(data.status)}</span>`;
        }
        value = left(default_formatter(value, row, column, data));
        if (column.fieldname === "missing_info" && data.missing_info) {
            return `<span style="color: var(--red-600);">${value}</span>`;
        }
        return value;
    },
};
