"""Demo employees with realistic (fictional) data for testing.

Create:
    bench --site SITE execute hr_toolkit.payroll.demo_employees.make --kwargs "{'company': 'Spry Dyeing'}"
Remove:
    bench --site SITE execute hr_toolkit.payroll.demo_employees.remove
"""
import frappe

DEMO_PREFIX = "DEMO-"
STRUCTURE = "Standard Salary - SD"

# first, last, father, gender, date_of_birth, date_of_joining, department, designation,
# employment_type, salary, blood_group, relieving_date
EMPLOYEES = [
    ("Muhammad", "Usman", "Abdul Ghafoor", "Male", "1990-03-12", "2019-04-01", "Production", "Production Manager", "Full-time", 180000, "B+", None),
    ("Ayesha", "Siddiqui", "Tariq Siddiqui", "Female", "1995-07-22", "2021-08-16", "Accounts", "Accountant", "Full-time", 85000, "A+", None),
    ("Ali", "Raza", "Muhammad Aslam", "Male", "1998-11-05", "2023-02-01", "Stitching", "Machine Operator", "Full-time", 38000, "O+", None),
    ("Bilal", "Ahmed", "Nazir Ahmed", "Male", "1996-01-19", "2022-06-10", "Cutting", "Cutting Master", "Full-time", 55000, "B-", None),
    ("Fatima", "Noor", "Ghulam Rasool", "Female", "1999-09-30", "2024-03-04", "HR", "HR Officer", "Full-time", 70000, "AB+", None),
    ("Hamza", "Iqbal", "Javed Iqbal", "Male", "2001-05-14", "2026-05-10", "Packing", "Packer", "Probation", 32000, "O+", None),
    ("Zain", "ul Abideen", "Shafqat Hussain", "Male", "1994-02-08", "2020-01-15", "Quality Control", "QC Inspector", "Full-time", 60000, "A-", None),
    ("Sana", "Batool", "Syed Akhtar Shah", "Female", "1997-12-25", "2022-11-01", "Admin", "Receptionist", "Full-time", 42000, "B+", None),
    ("Usama", "Tariq", "Tariq Mehmood", "Male", "2000-08-17", "2025-07-01", "Dyeing", "Dyeing Operator", "Contract", 40000, "O-", None),
    ("Hassan", "Ali", "Liaqat Ali", "Male", "1988-04-03", "2017-09-11", "Maintenance", "Electrician", "Full-time", 65000, "A+", None),
    ("Kashif", "Mehmood", "Mehmood ul Hassan", "Male", "1992-10-21", "2018-03-05", "Store", "Store Keeper", "Full-time", 58000, "B+", None),
    ("Rabia", "Khalid", "Khalid Pervaiz", "Female", "2002-06-11", "2026-04-01", "Stitching", "Machine Operator", "Probation", 33000, "AB-", None),
    ("Imran", "Shahzad", "Muhammad Shafi", "Male", "1985-12-01", "2015-05-20", "Production", "Supervisor", "Full-time", 95000, "O+", None),
    ("Adeel", "Anwar", "Anwar ul Haq", "Male", "1997-03-27", "2023-09-18", "Cutting", "Cutter", "Full-time", 40000, "B+", None),
    ("Maryam", "Aslam", "Muhammad Aslam Butt", "Female", "1998-01-09", "2024-10-07", "Accounts", "Accounts Assistant", "Full-time", 55000, "O+", None),
    ("Waqas", "Ahmad", "Bashir Ahmad", "Male", "1993-07-07", "2021-02-22", "Dyeing", "Dyeing Master", "Full-time", 90000, "A+", None),
    ("Shahid", "Nawaz", "Allah Ditta", "Male", "1980-09-15", "2016-08-01", "Admin", "Driver", "Full-time", 40000, "B-", None),
    ("Asad", "Mehmood", "Khalid Mehmood", "Male", "2003-04-29", "2026-08-03", "Packing", "Helper", "Probation", 30000, "O+", None),
    ("Nimra", "Shahid", "Shahid Iqbal", "Female", "2000-11-19", "2025-01-13", "Quality Control", "QC Inspector", "Full-time", 45000, "A+", None),
    ("Faisal", "Mehmood", "Mehmood Akhtar", "Male", "1991-05-02", "2019-11-04", "Stitching", "Line Supervisor", "Full-time", 70000, "AB+", "2026-09-12"),
    ("Junaid", "Akram", "Muhammad Akram", "Male", "1995-08-23", "2022-04-11", "Maintenance", "Mechanic", "Contract", 48000, "O-", None),
    ("Hira", "Fatima", "Zulfiqar Ali", "Female", "1996-02-14", "2023-05-29", "HR", "Payroll Officer", "Full-time", 75000, "B+", None),
    ("Naveed", "Akhtar", "Akhtar Hussain", "Male", "1989-10-10", "2018-07-23", "Store", "Store Incharge", "Full-time", 80000, "A-", None),
    ("Umer", "Farooq", "Farooq Ahmed", "Male", "1999-12-30", "2024-06-17", "Cutting", "Cutter", "Full-time", 39000, "O+", "2026-08-31"),
    ("Sadia", "Parveen", "Muhammad Yousaf", "Female", "1994-04-18", "2020-10-05", "Admin", "Admin Officer", "Full-time", 72000, "B+", None),
]

MOBILE_PREFIXES = ["0300", "0301", "0302", "0303", "0305", "0306", "0307", "0308",
                   "0310", "0312", "0315", "0321", "0333", "0345", "0346"]


def _ensure(doctype, name, values):
    if not frappe.db.exists(doctype, name):
        frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def _department(base, company, abbr):
    name = f"{base} - {abbr}"
    _ensure("Department", name, {"department_name": base, "parent_department": "All Departments", "company": company})
    return name


def make(company, structure=STRUCTURE):
    if frappe.db.exists("Employee", {"employee_number": ["like", f"{DEMO_PREFIX}%"]}):
        frappe.throw("Demo employees already exist. Run remove first.")

    abbr = frappe.db.get_value("Company", company, "abbr")
    holiday_list = frappe.db.get_value("Company", company, "default_holiday_list") \
        or frappe.db.get_value("Holiday List", {}, "name", order_by="creation desc")
    shift = "Admin Shift" if frappe.db.exists("Shift Type", "Admin Shift") \
        else frappe.db.get_value("Shift Type", {}, "name")

    rows = []
    for i, (first, last, father, gender, dob, doj, dept, designation, emp_type, salary, blood, relieving) in enumerate(EMPLOYEES, start=1):
        _ensure("Designation", designation, {"designation_name": designation})
        _ensure("Employment Type", emp_type, {"employee_type_name": emp_type})
        department = _department(dept, company, abbr)

        # Pakistani CNIC: last digit odd for male, even for female
        last_digit = (2 * i + 1) % 10 if gender == "Male" else (2 * i) % 10
        cnic = f"34603-{(1234567 + i * 104729) % 10000000:07d}-{last_digit}"
        mobile = f"{MOBILE_PREFIXES[i % len(MOBILE_PREFIXES)]}-{(7654321 + i * 90731) % 10000000:07d}"

        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": first,
            "last_name": last,
            "custom_father_name": father,
            "gender": gender,
            "date_of_birth": dob,
            "date_of_joining": doj,
            "company": company,
            "department": department,
            "designation": designation,
            "employment_type": emp_type,
            "cell_number": mobile,
            "custom_cnic": cnic,
            "blood_group": blood,
            "holiday_list": holiday_list,
            "default_shift": shift,
            "employee_number": f"{DEMO_PREFIX}{i:02d}",
            "status": "Left" if relieving else "Active",
            "relieving_date": relieving,
        })
        emp.insert(ignore_permissions=True)

        ssa = frappe.get_doc({
            "doctype": "Salary Structure Assignment",
            "employee": emp.name,
            "salary_structure": structure,
            "company": company,
            "from_date": doj,
            "base": salary,
        })
        ssa.insert(ignore_permissions=True)
        ssa.submit()
        rows.append((emp.name, emp.employee_name, department, designation, salary, emp.status))

    frappe.db.commit()
    for r in rows:
        print(f"{r[0]:16} {r[1]:22} {r[2]:24} {r[3]:20} {r[4]:>8,} {r[5]}")
    print(f"\n{len(rows)} demo employees created.")


def remove():
    employees = frappe.get_all("Employee", filters={"employee_number": ["like", f"{DEMO_PREFIX}%"]}, pluck="name")
    for name in employees:
        for ssa in frappe.get_all("Salary Structure Assignment", filters={"employee": name}, fields=["name", "docstatus"]):
            doc = frappe.get_doc("Salary Structure Assignment", ssa.name)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc("Salary Structure Assignment", ssa.name, ignore_permissions=True)
        frappe.delete_doc("Employee", name, ignore_permissions=True)
    frappe.db.commit()
    print(f"{len(employees)} demo employees removed.")
