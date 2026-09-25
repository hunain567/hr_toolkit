import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Deduction formula reads from Salary Slip fields that are filled
# by hr_toolkit.payroll.salary_slip before the formula is evaluated.
ABSENT_FORMULA = "round(base / fixed_working_days * deduct_days) if fixed_working_days else 0"

COMPONENTS = [
    {
        "name": "Monthly Salary",
        "abbr": "MS",
        "type": "Earning",
        "formula": "base",
        "remove_if_zero": 0,
        "do_not_include_in_total": 1,
        "description": "Salary as per Salary Structure Assignment. Display only, not included in totals.",
    },
    {
        "name": "Basic",
        "abbr": "B",
        "type": "Earning",
        "formula": "base",
        "remove_if_zero": 0,
        "do_not_include_in_total": 0,
        "description": "Full monthly salary. Not prorated by month length.",
    },
    {
        "name": "Attendance Deduction",
        "abbr": "AD",
        "type": "Deduction",
        "formula": ABSENT_FORMULA,
        "remove_if_zero": 1,
        "do_not_include_in_total": 0,
        "description": "Per day salary (Salary / Working Days from HR Toolkit Settings) x Deduction Days.",
    },
]

# Helper fields used by formulas. Hidden on the form.
CUSTOM_FIELDS = {
    "Salary Slip": [
        {
            "fieldname": "full_absent_days",
            "label": "Full Day Absents",
            "fieldtype": "Float",
            "insert_after": "absent_days",
            "read_only": 1,
            "hidden": 1,
            "default": "0",
            "description": "Attendance marked as Absent in this period",
        },
        {
            "fieldname": "hrt_unmarked_days",
            "label": "Unmarked Days",
            "fieldtype": "Float",
            "insert_after": "full_absent_days",
            "read_only": 1,
            "hidden": 1,
            "default": "0",
            "description": "Working days up to today with no attendance record",
        },
        {
            "fieldname": "deduct_days",
            "label": "Deduction Days",
            "fieldtype": "Float",
            "insert_after": "hrt_unmarked_days",
            "read_only": 1,
            "hidden": 1,
            "default": "0",
            "description": "Days deducted from salary as per HR Toolkit Settings",
        },
        {
            "fieldname": "fixed_working_days",
            "label": "Fixed Working Days",
            "fieldtype": "Int",
            "insert_after": "deduct_days",
            "read_only": 1,
            "hidden": 1,
            "description": "From HR Toolkit Settings",
        },
    ]
}

DEFAULT_SETTINGS = {
    "working_days": 26,
    "show_fixed_days_on_slip": 1,
    "count_unmarked_as_absent": 1,
    "exclude_holidays": 1,
    "count_half_day": 0,
    "half_day_value": 0.5,
    "deduct_before_joining": 0,
}


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, update=True)


def setup_settings():
    """Fill defaults only for settings never saved before. Never overwrite user changes."""
    if not frappe.db.exists("DocType", "HR Toolkit Settings"):
        return
    saved = set(
        frappe.db.sql_list("select field from `tabSingles` where doctype = 'HR Toolkit Settings'")
    )
    for key, value in DEFAULT_SETTINGS.items():
        if key not in saved:
            frappe.db.set_single_value("HR Toolkit Settings", key, value)
    frappe.clear_document_cache("HR Toolkit Settings", "HR Toolkit Settings")


def setup_payroll_settings():
    frappe.db.set_single_value("Payroll Settings", "payroll_based_on", "Attendance")


def setup_salary_components():
    for c in COMPONENTS:
        clash = frappe.db.get_value(
            "Salary Component",
            {"salary_component_abbr": c["abbr"], "name": ["!=", c["name"]]},
            "name",
        )
        if clash:
            frappe.throw(
                _("Abbreviation '{0}' is already used by Salary Component '{1}'. Please change it first.").format(
                    c["abbr"], clash
                )
            )

        if frappe.db.exists("Salary Component", c["name"]):
            doc = frappe.get_doc("Salary Component", c["name"])
        else:
            doc = frappe.new_doc("Salary Component")
            doc.salary_component = c["name"]

        doc.salary_component_abbr = c["abbr"]
        doc.type = c["type"]
        doc.depends_on_payment_days = 0
        doc.amount_based_on_formula = 1
        doc.formula = c["formula"]
        doc.remove_if_zero_valued = c["remove_if_zero"]
        doc.do_not_include_in_total = c["do_not_include_in_total"]
        doc.description = c["description"]
        doc.disabled = 0
        doc.flags.ignore_permissions = True
        doc.save()


def update_structure_formulas():
    """Sync app components into structures created by this app ('Standard Salary - XX').
    Updates existing rows and adds missing ones."""
    structures = frappe.get_all(
        "Salary Structure", filters={"name": ["like", "Standard Salary - %"]}, pluck="name"
    )
    for name in structures:
        ss = frappe.get_doc("Salary Structure", name)
        for c in COMPONENTS:
            table = "earnings" if c["type"] == "Earning" else "deductions"
            row = next((r for r in ss.get(table) if r.salary_component == c["name"]), None)
            if row:
                frappe.db.set_value("Salary Detail", row.name, {
                    "formula": c["formula"],
                    "amount_based_on_formula": 1,
                    "depends_on_payment_days": 0,
                    "do_not_include_in_total": c["do_not_include_in_total"],
                })
            else:
                new_row = ss.append(table, {
                    "salary_component": c["name"],
                    "abbr": c["abbr"],
                    "amount_based_on_formula": 1,
                    "formula": c["formula"],
                    "depends_on_payment_days": 0,
                    "do_not_include_in_total": c["do_not_include_in_total"],
                })
                new_row.idx = 0
                new_row.db_insert()


def create_salary_structure(company, structure_name=None, submit=True):
    abbr = frappe.db.get_value("Company", company, "abbr")
    currency = frappe.db.get_value("Company", company, "default_currency")
    structure_name = structure_name or f"Standard Salary - {abbr}"

    if frappe.db.exists("Salary Structure", structure_name):
        print(f"Salary Structure '{structure_name}' already exists.")
        return structure_name

    ss = frappe.new_doc("Salary Structure")
    ss.name = structure_name
    ss.company = company
    ss.currency = currency
    ss.payroll_frequency = "Monthly"
    ss.is_active = "Yes"

    for c in COMPONENTS:
        table = "earnings" if c["type"] == "Earning" else "deductions"
        ss.append(table, {
            "salary_component": c["name"],
            "abbr": c["abbr"],
            "amount_based_on_formula": 1,
            "formula": c["formula"],
            "depends_on_payment_days": 0,
            "do_not_include_in_total": c["do_not_include_in_total"],
        })

    ss.flags.ignore_permissions = True
    ss.insert()
    if submit:
        ss.submit()

    print(f"Salary Structure '{structure_name}' created.")
    return structure_name


def run(company=None):
    """bench --site SITE execute hr_toolkit.payroll.setup.run --kwargs "{'company': 'Company Name'}" """
    setup_custom_fields()
    setup_settings()
    setup_payroll_settings()
    setup_salary_components()
    update_structure_formulas()
    if company:
        create_salary_structure(company)
    frappe.db.commit()
    print("HR Toolkit payroll setup completed.")
