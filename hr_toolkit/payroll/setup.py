import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Basic reads the earned amount calculated by hr_toolkit.payroll.salary_slip
# before salary component formulas are evaluated.
BASIC_FORMULA = "hrt_earned_basic"

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
        "formula": BASIC_FORMULA,
        "remove_if_zero": 0,
        "do_not_include_in_total": 0,
        "description": "Earned basic salary as per HR Toolkit Settings. See Calculation Details on the Salary Slip.",
    },
]

# Components retired by this app and removed from app-created structures.
REMOVED_COMPONENTS = []


def _ro(fieldname, label, fieldtype, insert_after, **extra):
    df = {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": fieldtype,
        "insert_after": insert_after,
        "read_only": 1,
        "hidden": 0,
        "description": "",
    }
    df.update(extra)
    return df


CUSTOM_FIELDS = {
    "Salary Slip": [
        {
            "fieldname": "hrt_calc_section",
            "label": "Calculation Details",
            "fieldtype": "Section Break",
            "insert_after": "payment_days",
            "collapsible": 1,
        },
        _ro("hrt_calculation_method", "Calculation Method", "Data", "hrt_calc_section"),
        _ro("hrt_base_salary", "Monthly Salary", "Currency", "hrt_calculation_method", options="currency"),
        _ro("fixed_working_days", "Daily Rate Divisor", "Int", "hrt_base_salary"),
        _ro("hrt_daily_rate", "Daily Rate", "Currency", "fixed_working_days", options="currency"),
        _ro("hrt_full_period", "Full Period Employee", "Check", "hrt_daily_rate"),
        _ro("hrt_earned_basic", "Earned Basic", "Currency", "hrt_full_period", options="currency", bold=1),
        {"fieldname": "hrt_calc_cb", "fieldtype": "Column Break", "insert_after": "hrt_earned_basic"},
        _ro("hrt_payable_days", "Payable Days", "Float", "hrt_calc_cb", bold=1),
        _ro("deduct_days", "Chargeable Days", "Float", "hrt_payable_days"),
        _ro("hrt_present_days", "Present Days", "Float", "deduct_days"),
        _ro("hrt_paid_leave_days", "Paid Leave Days", "Float", "hrt_present_days"),
        _ro("full_absent_days", "Absent Days (Marked)", "Float", "hrt_paid_leave_days"),
        _ro("hrt_unmarked_days", "Unmarked Days", "Float", "full_absent_days"),
        _ro("hrt_lwp_days", "Leave Without Pay Days", "Float", "hrt_unmarked_days"),
        _ro("hrt_half_days", "Half Days", "Float", "hrt_lwp_days"),
        _ro("hrt_sandwich_days", "Sandwich Weekly Offs", "Float", "hrt_half_days"),
        _ro("hrt_weekly_off_days", "Weekly Offs", "Float", "hrt_sandwich_days"),
        _ro("hrt_holiday_days", "Holidays", "Float", "hrt_weekly_off_days"),
        _ro("hrt_outside_days", "Days Outside Employment", "Float", "hrt_holiday_days"),
        _ro("hrt_future_days", "Days After Cut-off", "Float", "hrt_outside_days"),
    ]
}

DEFAULT_SETTINGS = {
    "calculation_method": "26-Day Basis",
    "rounding_precision": 0,
    "show_fixed_days_on_slip": 1,
    "weekly_off_day": "Sunday",
    "weekly_off_paid": 1,
    "sandwich_rule": 0,
    "holidays_paid": 1,
    "exclude_holidays": 1,
    "count_unmarked_as_absent": 1,
    "attendance_cutoff": "Today",
    "deduct_lwp": 1,
    "count_half_day": 0,
    "half_day_value": 0.5,
    "proration_basis": "Working Days",
}


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.db.updatedb("Salary Slip")


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
    Updates existing rows, adds missing ones and removes retired components.
    Other rows added by the user are not touched."""
    structures = frappe.get_all(
        "Salary Structure", filters={"name": ["like", "Standard Salary - %"]}, pluck="name"
    )
    for name in structures:
        ss = frappe.get_doc("Salary Structure", name)

        for comp in REMOVED_COMPONENTS:
            frappe.db.delete(
                "Salary Detail",
                {"parenttype": "Salary Structure", "parent": name, "salary_component": comp},
            )

        for c in COMPONENTS:
            table = "earnings" if c["type"] == "Earning" else "deductions"
            row = None
            for r in ss.get(table):
                if r.salary_component == c["name"]:
                    row = r
                    break
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
