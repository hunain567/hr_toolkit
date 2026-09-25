import frappe
from hr_toolkit.payroll.setup import (
    setup_custom_fields,
    setup_payroll_settings,
    setup_salary_components,
    setup_settings,
)


def after_install():
    try:
        setup_custom_fields()
        setup_settings()
        setup_payroll_settings()
        setup_salary_components()
        frappe.db.commit()
    except Exception:
        frappe.log_error(title="HR Toolkit: after_install failed")
        print("HR Toolkit setup failed. Please check Error Log.")


def after_migrate():
    try:
        setup_custom_fields()
        setup_settings()
    except Exception:
        frappe.log_error(title="HR Toolkit: after_migrate failed")
