import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Per day = salary / 26 (hamesha).
# Sirf "Absent" din katte hain (full_absent_days).
# Leave, Half Day, Sunday/Holiday par koi deduction nahi.
ABSENT_FORMULA = "round(base / 26 * (full_absent_days if full_absent_days < 26 else 26))"

COMPONENTS = [
    {
        "name": "Basic",
        "abbr": "B",
        "type": "Earning",
        "formula": "base",
        "remove_if_zero": 0,
        "description": "Full monthly salary (gross). Month days se prorate nahi hoti.",
    },
    {
        "name": "Attendance Deduction",
        "abbr": "AD",
        "type": "Deduction",
        "formula": ABSENT_FORMULA,
        "remove_if_zero": 1,
        "description": "Per day = salary / 26, sirf full day Absent par deduction.",
    },
]

CUSTOM_FIELDS = {
    "Salary Slip": [
        {
            "fieldname": "full_absent_days",
            "label": "Full Day Absents",
            "fieldtype": "Float",
            "insert_after": "absent_days",
            "read_only": 1,
            "default": "0",
            "description": "Sirf Absent status wale din (Half Day, Leave, Holiday shamil nahi)",
        }
    ]
}


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, update=True)


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
                f"Abbr '{c['abbr']}' pehle se '{clash}' component mein use ho raha hai. "
                f"Pehle us ka Abbr change karein."
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
        doc.description = c["description"]
        doc.disabled = 0
        doc.flags.ignore_permissions = True
        doc.save()


def create_salary_structure(company, structure_name=None, submit=True):
    abbr = frappe.db.get_value("Company", company, "abbr")
    currency = frappe.db.get_value("Company", company, "default_currency")
    structure_name = structure_name or f"Standard Salary - {abbr}"

    if frappe.db.exists("Salary Structure", structure_name):
        print(f"Salary Structure '{structure_name}' pehle se mojood hai.")
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
        })

    ss.flags.ignore_permissions = True
    ss.insert()
    if submit:
        ss.submit()

    print(f"Salary Structure '{structure_name}' ban gaya.")
    return structure_name


def run(company=None):
    """bench --site SITE execute hr_toolkit.payroll.setup.run --kwargs "{'company': 'Company Name'}" """
    setup_custom_fields()
    setup_payroll_settings()
    setup_salary_components()
    if company:
        create_salary_structure(company)
    frappe.db.commit()
    print("✅ HR Toolkit payroll setup mukammal.")
