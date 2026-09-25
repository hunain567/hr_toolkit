import frappe
from frappe.utils import getdate


def set_full_absent_days(doc, method=None):
    """Salary Slip save hone se pehle: sirf full day Absent gino, holidays nikaal ke."""
    if not (doc.employee and doc.start_date and doc.end_date):
        return

    absent_dates = frappe.get_all(
        "Attendance",
        filters={
            "employee": doc.employee,
            "docstatus": 1,
            "status": "Absent",
            "attendance_date": ["between", [doc.start_date, doc.end_date]],
        },
        pluck="attendance_date",
    )

    holidays = set()
    try:
        from hrms.hr.utils import get_holiday_dates_for_employee
        holidays = {
            getdate(d)
            for d in get_holiday_dates_for_employee(doc.employee, doc.start_date, doc.end_date)
        }
    except Exception:
        pass

    doc.full_absent_days = len([d for d in absent_dates if getdate(d) not in holidays])
