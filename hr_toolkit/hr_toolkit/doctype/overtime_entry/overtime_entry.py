import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, formatdate, get_first_day, get_last_day, getdate

from hr_toolkit.payroll.attendance import compute_overtime, get_employee_shift, get_overtime_settings
from hr_toolkit.payroll.salary_slip import (
    FIXED_DIVISORS,
    get_base_salary,
    get_off_days,
    get_overtime_policy,
    get_settings,
)
from hr_toolkit.payroll.shift import get_shift_types


def get_divisor(s, employee, day):
    """Daily rate divisor for the month of the overtime date, as per HR Toolkit Settings."""
    if s.method in FIXED_DIVISORS:
        return FIXED_DIVISORS[s.method]
    start, end = getdate(get_first_day(day)), getdate(get_last_day(day))
    days = date_diff(end, start) + 1
    if s.method == "Actual Working Days":
        weekly, holidays = get_off_days(employee, start, end, s.weekly_off_day)
        return days - len(weekly | holidays)
    return days


class OvertimeEntry(Document):
    def validate(self):
        self.validate_rows()
        self.validate_duplicate_entries()
        self.set_amounts()

    def on_submit(self):
        self.validate_salary_slips(_("submit"))

    def on_cancel(self):
        self.validate_salary_slips(_("cancel"))

    def validate_rows(self):
        seen = set()
        for row in self.employees:
            if row.employee in seen:
                frappe.throw(_("Row #{0}: Employee {1} is added more than once.").format(row.idx, row.employee))
            seen.add(row.employee)
            if flt(row.overtime_hours) < 0:
                frappe.throw(_("Row #{0}: Approved Overtime Hours cannot be negative.").format(row.idx))
            if frappe.db.get_value("Employee", row.employee, "company") != self.company:
                frappe.throw(_("Row #{0}: Employee {1} does not belong to {2}.").format(row.idx, row.employee, self.company))

    def validate_duplicate_entries(self):
        employees = [row.employee for row in self.employees]
        if not employees:
            return
        duplicates = frappe.db.sql(
            """select d.employee, e.name from `tabOvertime Entry Detail` d
               inner join `tabOvertime Entry` e on e.name = d.parent
               where e.docstatus = 1 and e.overtime_date = %s and e.name != %s and d.employee in %s""",
            (self.overtime_date, self.name or "", tuple(employees)),
            as_dict=True,
        )
        if duplicates:
            lines = "<br>".join(f"{d.employee} ({d.name})" for d in duplicates)
            frappe.throw(
                _("Overtime for these employees on {0} is already submitted:<br>{1}").format(
                    formatdate(self.overtime_date), lines
                ),
                title=_("Duplicate Overtime"),
            )

    def validate_salary_slips(self, action):
        employees = [row.employee for row in self.employees]
        if not employees:
            return
        slips = frappe.get_all(
            "Salary Slip",
            filters={
                "employee": ["in", employees],
                "docstatus": 1,
                "start_date": ["<=", self.overtime_date],
                "end_date": [">=", self.overtime_date],
            },
            fields=["name", "employee"],
        )
        if slips:
            lines = "<br>".join(f"{s.employee} ({s.name})" for s in slips)
            frappe.throw(
                _("Cannot {0}: submitted Salary Slip exists for this date. Cancel the Salary Slip first.<br>{1}").format(
                    action, lines
                ),
                title=_("Salary Slip Submitted"),
            )

    def set_amounts(self):
        """Monthly Salary, Hourly Rate, Rate Multiplier, Overtime Amount and Eligibility for every row.
        Same rules as the Salary Slip, so the amounts here are what the salary will pay."""
        s = get_settings()
        shift_types = get_shift_types()
        day = getdate(self.overtime_date)

        for row in self.employees:
            employee = frappe.db.get_value(
                "Employee", row.employee,
                ["name", "company", "department", "designation", "grade"],
                as_dict=True,
            )
            base = get_base_salary(row.employee, None, day)
            policy, reason = get_overtime_policy(s, employee, base)

            if not row.shift:
                row.shift = get_employee_shift(row.employee, day)
            st = shift_types.get(row.shift)
            divisor = get_divisor(s, row.employee, day)
            daily_rate = base / divisor if divisor else 0
            hourly = daily_rate / st.hours if st and st.hours > 0 else 0

            multiplier = 0
            if policy:
                multiplier = st.multiplier if st and st.multiplier > 0 else flt(policy.rate_multiplier) or 1
            if policy and not hourly:
                reason = "Shift not found"

            row.monthly_salary = base
            row.hourly_rate = flt(hourly, 2)
            row.rate_multiplier = multiplier
            row.overtime_amount = flt(hourly * flt(row.overtime_hours) * multiplier, s.precision)
            row.eligibility = reason

        self.total_overtime_hours = flt(sum(flt(r.overtime_hours) for r in self.employees), 2)
        self.total_overtime_amount = flt(sum(flt(r.overtime_amount) for r in self.employees), 2)

    @frappe.whitelist()
    def get_employees(self):
        """Fill Employees with everyone who has overtime on Overtime Date, calculated from Employee Checkin."""
        if not (self.company and self.overtime_date):
            frappe.throw(_("Please select Company and Overtime Date first."))

        day = getdate(self.overtime_date)
        filters = {"company": self.company, "status": "Active"}
        if self.department:
            filters["department"] = self.department
        employees = frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "department"])
        self.set("employees", [])
        if not employees:
            self.set_amounts()
            return 0

        with_logs = set(frappe.get_all(
            "Employee Checkin",
            filters={
                "employee": ["in", [e.name for e in employees]],
                "time": ["between", [add_days(day, -1), add_days(day, 2)]],
            },
            pluck="employee",
            distinct=True,
        ))

        settings = get_overtime_settings()
        for e in employees:
            if e.name not in with_logs:
                continue
            attendance = frappe.db.get_value(
                "Attendance", {"employee": e.name, "attendance_date": day, "docstatus": 1},
                ["name", "shift"], as_dict=True,
            )
            shift = get_employee_shift(e.name, day, attendance.shift if attendance else None)
            if self.shift_type and shift != self.shift_type:
                continue
            result = compute_overtime(e.name, day, shift, settings)
            if not result or result.overtime_hours <= 0:
                continue
            self.append("employees", {
                "employee": e.name,
                "employee_name": e.employee_name,
                "department": e.department,
                "shift": shift,
                "in_time": result.in_time,
                "out_time": result.out_time,
                "working_hours": result.working_hours,
                "calculated_hours": result.overtime_hours,
                "overtime_hours": result.overtime_hours,
                "attendance": attendance.name if attendance else None,
            })

        self.set_amounts()
        return len(self.employees)
