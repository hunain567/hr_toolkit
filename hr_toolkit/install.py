import frappe
from hr_toolkit.payroll.setup import (
    setup_custom_fields,
    setup_payroll_settings,
    setup_salary_components,
)


def after_install():
    try:
        setup_custom_fields()
        setup_payroll_settings()
        setup_salary_components()
        frappe.db.commit()
    except Exception:
        frappe.log_error(title="HR Toolkit after_install failed")
        print("⚠️ HR Toolkit setup mein masla aaya, Error Log check karein.")
