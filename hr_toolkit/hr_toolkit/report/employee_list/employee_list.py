import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.utils import flt, getdate, today

SALARY_ROLES = {"System Manager", "HR Manager"}

GROUP_FIELDS = {
    "Department": "department",
    "Designation": "designation",
    "Employment Type": "employment_type",
    "Gender": "gender",
    "Status": "status",
}

REQUIRED_INFO = [
    ("father_name", "Father Name"),
    ("cnic", "CNIC"),
    ("cell_number", "Mobile"),
    ("date_of_birth", "Date of Birth"),
    ("blood_group", "Blood Group"),
    ("department", "Department"),
    ("designation", "Designation"),
]


def execute(filters=None):
    filters = frappe._dict(filters or {})
    meta = frappe.get_meta("Employee")
    father_field = find_field(meta, ["father_name", "custom_father_name", "custom_fathers_name"], ["father"])
    cnic_field = find_field(meta, ["cnic", "custom_cnic", "custom_cnic_no", "custom_cnic_number"], ["cnic"])
    show_salary = bool(SALARY_ROLES & set(frappe.get_roles()))

    data = get_data(filters, father_field, cnic_field, show_salary)
    summary = get_summary(data, show_salary)
    data = group_rows(data, filters.group_by, show_salary)

    return get_columns(show_salary), data, None, None, summary


def find_field(meta, fieldnames, label_words):
    """Custom fields differ per site: try known fieldnames first, then match by label."""
    for fieldname in fieldnames:
        if meta.has_field(fieldname):
            return fieldname
    for df in meta.fields:
        label = (df.label or "").lower()
        if df.fieldtype in ("Data", "Small Text", "Read Only") and all(w in label for w in label_words):
            return df.fieldname
    return None


def col(label, fieldname, fieldtype, width, align, options=None):
    c = {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width, "align": align}
    if options:
        c["options"] = options
    return c


def get_columns(show_salary):
    columns = [
        col("Employee ID", "employee", "Link", 140, "left", "Employee"),
        col("Employee Name", "employee_name", "Data", 190, "left"),
        col("Father Name", "father_name", "Data", 190, "left"),
        col("Gender", "gender", "Data", 85, "left"),
        col("Designation", "designation", "Data", 170, "left"),
        col("Department", "department", "Data", 190, "left"),
        col("Employee Type", "employment_type", "Data", 135, "left"),
        col("Date of Joining", "date_of_joining", "Date", 125, "left"),
        col("Date of Relieving", "relieving_date", "Date", 140, "left"),
        
        col("Date of Birth", "date_of_birth", "Date", 115, "left"),
        col("Age", "age", "Int", 60, "left"),
        col("CNIC", "cnic", "Data", 150, "left"),
        col("Mobile", "cell_number", "Data", 130, "left"),
    ]
    if show_salary:
        columns.append(col("Salary", "salary", "Currency", 130, "left"))
    columns += [
        col("Status", "status", "Data", 100, "left"),
        col("Blood Group", "blood_group", "Data", 120, "left"),
        col("Missing Information", "missing_info", "Data", 280, "left"),
    ]
    return columns


def get_data(filters, father_field, cnic_field, show_salary):
    conditions = {}
    for key in ("company", "status", "department", "designation", "employment_type", "gender", "blood_group"):
        if filters.get(key):
            conditions[key] = filters.get(key)
    if filters.joining_from and filters.joining_to:
        conditions["date_of_joining"] = ["between", [filters.joining_from, filters.joining_to]]
    elif filters.joining_from:
        conditions["date_of_joining"] = [">=", filters.joining_from]
    elif filters.joining_to:
        conditions["date_of_joining"] = ["<=", filters.joining_to]

    fields = [
        "name as employee", "employee_name", "gender", "designation", "department",
        "employment_type", "date_of_joining", "relieving_date", "date_of_birth",
        "cell_number", "status", "blood_group",
    ]
    if father_field:
        fields.append(f"`{father_field}` as father_name")
    if cnic_field:
        fields.append(f"`{cnic_field}` as cnic")

    data = frappe.get_all("Employee", filters=conditions, fields=fields, order_by="name asc")
    salaries = get_current_salaries() if show_salary and data else {}
    now = getdate(today())

    out = []
    for row in data:
        row.indent = 0
        if row.date_of_birth:
            row.age = relativedelta(now, getdate(row.date_of_birth)).years
        if row.date_of_joining:
            end = getdate(row.relieving_date) if row.relieving_date else now
            diff = relativedelta(end, getdate(row.date_of_joining))
            row.service = f"{diff.years} Y {diff.months} M"
        row.missing_info = ", ".join(label for field, label in REQUIRED_INFO if not row.get(field))

        if show_salary:
            row.salary = flt(salaries.get(row.employee))
            if filters.salary_from and row.salary < flt(filters.salary_from):
                continue
            if filters.salary_to and row.salary > flt(filters.salary_to):
                continue
        if filters.only_missing and not row.missing_info:
            continue
        out.append(row)
    return out


def get_current_salaries():
    """Base from the latest submitted Salary Structure Assignment up to today, per employee."""
    rows = frappe.db.sql(
        """select ssa.employee, ssa.base
           from `tabSalary Structure Assignment` ssa
           inner join (
               select employee, max(from_date) as from_date
               from `tabSalary Structure Assignment`
               where docstatus = 1 and from_date <= %s
               group by employee
           ) latest on latest.employee = ssa.employee and latest.from_date = ssa.from_date
           where ssa.docstatus = 1""",
        (today(),),
        as_dict=True,
    )
    return {r.employee: r.base for r in rows}


def get_summary(data, show_salary):
    active = [r for r in data if r.status == "Active"]
    missing = len([r for r in data if r.missing_info])
    summary = [
        {"value": len(data), "label": _("Total Employees"), "datatype": "Int", "indicator": "Blue"},
        {"value": len(active), "label": _("Active"), "datatype": "Int", "indicator": "Green"},
        {"value": len([r for r in data if r.status == "Left"]), "label": _("Left"), "datatype": "Int", "indicator": "Red"},
        {"value": len([r for r in data if r.gender == "Male"]), "label": _("Male"), "datatype": "Int", "indicator": "Blue"},
        {"value": len([r for r in data if r.gender == "Female"]), "label": _("Female"), "datatype": "Int", "indicator": "Purple"},
    ]
    if show_salary:
        summary.append({
            "value": sum(flt(r.salary) for r in active),
            "label": _("Monthly Salary (Active)"), "datatype": "Currency", "indicator": "Blue",
        })
    summary.append({
        "value": missing, "label": _("Missing Information"), "datatype": "Int",
        "indicator": "Orange" if missing else "Green",
    })
    return summary


def group_rows(data, group_by, show_salary):
    field = GROUP_FIELDS.get(group_by)
    if not field:
        return data
    groups = {}
    for row in data:
        groups.setdefault(row.get(field) or _("Not Set"), []).append(row)

    out = []
    for key in sorted(groups):
        rows = groups[key]
        header = frappe._dict(employee_name=f"{key} ({len(rows)})", indent=0, is_group=1)
        if show_salary:
            header.salary = sum(flt(r.salary) for r in rows)
        out.append(header)
        for row in rows:
            row.indent = 1
            out.append(row)
    return out
