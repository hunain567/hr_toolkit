"""Demo Employee Checkins for testing overtime.

Create:
    bench --site SITE execute hr_toolkit.payroll.demo_checkins.make --kwargs "{'employee': 'HR-EMP-00001', 'start': '2026-10-01', 'end': '2026-10-16'}"
Remove demo checkins (and reset overtime on those days):
    bench --site SITE execute hr_toolkit.payroll.demo_checkins.remove --kwargs "{'employee': 'HR-EMP-00001', 'start': '2026-10-01', 'end': '2026-10-16'}"
"""
from datetime import timedelta

import frappe
from frappe.utils import add_days, get_datetime, getdate, to_timedelta

from hr_toolkit.payroll.attendance import get_overtime_settings, set_overtime_from_checkins

DEMO_DEVICE = "HRT-DEMO"
# Minutes stayed after shift end, day by day
EXTRA_MINUTES = [0, 60, 125, 30, 95, 0, 150, 45, 180, 20, 70, 0, 110, 15]


def make(employee, start, end):
    if not (get_overtime_settings().enabled and get_overtime_settings().from_checkin):
        frappe.throw("Please enable 'Enable Overtime' and 'Calculate Overtime from Employee Checkin' in HR Toolkit Settings.")

    emp = frappe.db.get_value("Employee", employee, ["company", "default_shift"], as_dict=True)
    if not emp.default_shift:
        frappe.throw(f"Please set a Default Shift on Employee {employee} first.")
    st = frappe.db.get_value("Shift Type", emp.default_shift, ["start_time", "end_time"], as_dict=True)

    rows, i = [], 0
    day = getdate(start)
    while day <= getdate(end):
        existing = frappe.db.get_value(
            "Attendance", {"employee": employee, "attendance_date": day, "docstatus": 1},
            ["name", "status"], as_dict=True,
        )
        if day.strftime("%A") == "Sunday" or (existing and existing.status != "Present"):
            day = getdate(add_days(day, 1))
            continue

        base = get_datetime(day)
        shift_start = base + to_timedelta(st.start_time)
        shift_end = base + to_timedelta(st.end_time)
        if shift_end <= shift_start:
            shift_end += timedelta(days=1)

        extra = EXTRA_MINUTES[i % len(EXTRA_MINUTES)]
        i += 1
        in_time = shift_start - timedelta(minutes=5)
        out_time = shift_end + timedelta(minutes=extra)

        for t, log_type in ((in_time, "IN"), (out_time, "OUT")):
            if not frappe.db.exists("Employee Checkin", {"employee": employee, "time": t}):
                frappe.get_doc({
                    "doctype": "Employee Checkin", "employee": employee,
                    "time": t, "log_type": log_type, "device_id": DEMO_DEVICE,
                }).insert(ignore_permissions=True)

        if existing:
            att = frappe.get_doc("Attendance", existing.name)
            set_overtime_from_checkins(att)
            att.db_set({
                "in_time": att.in_time, "out_time": att.out_time,
                "working_hours": att.working_hours, "overtime_hours": att.overtime_hours,
            }, update_modified=False)
        else:
            att = frappe.get_doc({
                "doctype": "Attendance", "employee": employee, "company": emp.company,
                "attendance_date": day, "status": "Present",
            })
            att.insert(ignore_permissions=True)
            att.submit()

        rows.append((day, in_time, out_time, att.working_hours, att.overtime_hours))
        day = getdate(add_days(day, 1))

    frappe.db.commit()
    print(f"{'Date':12} {'In':20} {'Out':20} {'Worked':>7} {'OT':>5}")
    total = 0
    for d, a, b, w, ot in rows:
        total += ot or 0
        print(f"{str(d):12} {str(a):20} {str(b):20} {w:>7} {ot:>5}")
    print(f"\nTotal overtime hours: {total}")


def remove(employee, start, end):
    frappe.db.delete("Employee Checkin", {
        "employee": employee, "device_id": DEMO_DEVICE,
        "time": ["between", [get_datetime(start), get_datetime(add_days(end, 2))]],
    })
    frappe.db.sql(
        """update `tabAttendance` set overtime_hours = 0
           where employee = %s and attendance_date between %s and %s""",
        (employee, start, end),
    )
    frappe.db.commit()
    print("Demo checkins removed and overtime reset.")
