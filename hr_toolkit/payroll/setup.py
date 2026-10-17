import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Basic and Over Time read amounts calculated by hr_toolkit.payroll.salary_slip
# before salary component formulas are evaluated.
BASIC_FORMULA = "hrt_earned_basic"
OVERTIME_FORMULA = "hrt_overtime_amount"

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
    {
        "name": "Over Time",
        "abbr": "OT",
        "type": "Earning",
        "formula": OVERTIME_FORMULA,
        "remove_if_zero": 1,
        "do_not_include_in_total": 0,
        "description": "Daily Rate / Shift Hours x Overtime Hours (from Attendance) x Overtime Rate Multiplier.",
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
        # Shown next to the standard Absent Days field
        _ro("full_absent_days", "Absent Days (Marked)", "Float", "absent_days"),
        _ro("hrt_unmarked_days", "Unmarked Days", "Float", "full_absent_days"),
        # Calculation Details section
        {
            "fieldname": "hrt_calc_section",
            "label": "Calculation Details",
            "fieldtype": "Section Break",
            "insert_after": "payment_days",
            "collapsible": 1,
            "hidden": 0,
        },
        _ro("hrt_calculation_method", "Calculation Method", "Data", "hrt_calc_section"),
        _ro("hrt_base_salary", "Monthly Salary", "Currency", "hrt_calculation_method", options="currency"),
        _ro("fixed_working_days", "Daily Rate Divisor", "Int", "hrt_base_salary"),
        _ro("hrt_daily_rate", "Daily Rate", "Currency", "fixed_working_days", options="currency"),
        _ro("hrt_full_period", "Full Period Employee", "Check", "hrt_daily_rate"),
        _ro("hrt_earned_basic", "Earned Basic", "Currency", "hrt_full_period", options="currency", bold=1),
        _ro("hrt_hourly_rate", "Hourly Rate (Default Shift)", "Currency", "hrt_earned_basic", options="currency"),
        _ro("hrt_overtime_hours", "Overtime Hours", "Float", "hrt_hourly_rate"),
        _ro("hrt_overtime_amount", "Overtime Amount", "Currency", "hrt_overtime_hours", options="currency", bold=1),
        _ro("hrt_overtime_eligibility", "Overtime Eligibility", "Data", "hrt_overtime_amount"),
        {"fieldname": "hrt_calc_cb", "fieldtype": "Column Break", "insert_after": "hrt_overtime_eligibility", "hidden": 0},
        _ro("hrt_payable_days", "Payable Days", "Float", "hrt_calc_cb", bold=1),
        _ro("deduct_days", "Chargeable Days", "Float", "hrt_payable_days"),
        _ro("hrt_present_days", "Present Days", "Float", "deduct_days"),
        _ro("hrt_paid_leave_days", "Paid Leave Days", "Float", "hrt_present_days"),
        _ro("hrt_lwp_days", "Leave Without Pay Days", "Float", "hrt_paid_leave_days"),
        _ro("hrt_half_days", "Half Days", "Float", "hrt_lwp_days"),
        _ro("hrt_sandwich_days", "Sandwich Weekly Offs", "Float", "hrt_half_days"),
        _ro("hrt_weekly_off_days", "Weekly Offs", "Float", "hrt_sandwich_days"),
        _ro("hrt_holiday_days", "Holidays", "Float", "hrt_weekly_off_days"),
        _ro("hrt_outside_days", "Days Outside Employment", "Float", "hrt_holiday_days"),
        _ro("hrt_future_days", "Days After Cut-off", "Float", "hrt_outside_days"),
    ],
    "Employee": [
        {
            "fieldname": "hrt_salary",
            "label": "Salary",
            "fieldtype": "Currency",
            "options": "salary_currency",
            "insert_after": "ctc",
            "read_only": 1,
            "bold": 1,
            "description": "Monthly salary from the current Salary Structure Assignment.",
        },
    ],
    "Attendance": [
        {
            "fieldname": "overtime_hours",
            "label": "Overtime Hours",
            "fieldtype": "Float",
            "insert_after": "status",
            "description": "Calculated from Employee Checkin (information only). Salary uses submitted Overtime Entry.",
        },
    ],
    "Shift Type": [
        {"fieldname": "hrt_break_start", "label": "Break Start", "fieldtype": "Time", "insert_after": "end_time"},
        {"fieldname": "hrt_break_end", "label": "Break End", "fieldtype": "Time", "insert_after": "hrt_break_start"},
        _ro("hrt_break_minutes", "Break (Minutes)", "Int", "hrt_break_end"),
        _ro("hrt_shift_hours", "Shift Hours", "Float", "hrt_break_minutes",
            description="End Time - Start Time - Break. Used for the overtime hourly rate."),
        {
            "fieldname": "hrt_overtime_multiplier",
            "label": "Overtime Rate Multiplier",
            "fieldtype": "Float",
            "insert_after": "hrt_shift_hours",
            "description": "1 = Single, 2 = Double. Leave 0 to use the default from HR Toolkit Settings.",
        },
    ],
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
    "enable_overtime": 1,
    "overtime_from_checkin": 1,
    "overtime_rounding": 1,
    "overtime_min_minutes": 30,
    "overtime_round_minutes": 60,
}

PAYMENT_DAYS_LEFT = ["total_working_days", "payment_days", "absent_days"]
PAYMENT_DAYS_RIGHT = ["full_absent_days", "hrt_unmarked_days", "leave_without_pay"]


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    for doctype in CUSTOM_FIELDS:
        frappe.db.updatedb(doctype)
    setup_payment_days_layout()
    setup_property_setters()


def setup_payment_days_layout():
    """Arrange the Payment Days section of Salary Slip:
    left column  - Working Days, Payment Days, Absent Days
    right column - Absent Days (Marked), Unmarked Days, Leave Without Pay
    Uses a field_order Property Setter (same as Customize Form)."""
    import json
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    # Rebuild from the standard order so newly added fields are placed by insert_after
    frappe.db.delete("Property Setter", {"doc_type": "Salary Slip", "property": "field_order"})
    frappe.clear_cache(doctype="Salary Slip")
    meta = frappe.get_meta("Salary Slip")
    order = [df.fieldname for df in meta.fields]
    block = PAYMENT_DAYS_LEFT + PAYMENT_DAYS_RIGHT

    missing = [f for f in block if f not in order]
    if missing:
        print("Payment Days layout skipped, fields not found:", missing)
        return

    positions = [order.index(f) for f in block]
    first, last = min(positions), max(positions)

    column_break = None
    for f in order[first:last + 1]:
        if meta.get_field(f).fieldtype == "Column Break":
            column_break = f
            break
    if not column_break:
        print("Payment Days layout skipped, no column break found in the section.")
        return

    remove = set(block + [column_break])
    rest = [f for f in order if f not in remove]
    insert_at = len([f for f in order[:first] if f not in remove])
    new_order = (
        rest[:insert_at] + PAYMENT_DAYS_LEFT + [column_break] + PAYMENT_DAYS_RIGHT + rest[insert_at:]
    )

    make_property_setter(
        "Salary Slip", None, "field_order", json.dumps(new_order), "Data", for_doctype=True
    )
    frappe.clear_cache(doctype="Salary Slip")
    print("Payment Days layout updated.")


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
                new_row.idx = len(ss.get(table))
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


def setup_property_setters():
    """Hide Cost to Company (CTC) on Employee; Salary comes from Salary Structure Assignment."""
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    make_property_setter("Employee", "ctc", "hidden", 1, "Check")
    frappe.clear_cache(doctype="Employee")
