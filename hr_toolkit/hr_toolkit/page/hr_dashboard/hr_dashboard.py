import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, get_last_day, getdate, nowdate

SALARY_ROLES = {"System Manager", "HR Manager"}
SALARY_BANDS = [
    (0, 30000, "< 30k"),
    (30000, 50000, "30k - 50k"),
    (50000, 75000, "50k - 75k"),
    (75000, 100000, "75k - 100k"),
    (100000, None, "100k +"),
]


def _short(name):
    return (name or _("Not Set")).rsplit(" - ", 1)[0]


@frappe.whitelist()
def get_dashboard_data(company=None, date=None):
    frappe.only_for(["System Manager", "HR Manager", "HR User"])
    company = company or frappe.defaults.get_user_default("Company")
    day = getdate(date or nowdate())
    start, end = getdate(get_first_day(day)), getdate(get_last_day(day))
    show_salary = bool(SALARY_ROLES & set(frappe.get_roles()))

    employees = frappe.get_all(
        "Employee",
        filters={"company": company},
        fields=["name", "employee_name", "status", "gender", "department", "designation",
                "date_of_joining", "relieving_date", "date_of_birth"],
    )
    active = [e for e in employees if e.status == "Active"]
    active_names = {e.name for e in active}

    data = frappe._dict(
        company=company,
        date=str(day),
        month_label=day.strftime("%B %Y"),
        currency=frappe.get_cached_value("Company", company, "default_currency"),
        show_salary=show_salary,
    )

    # ---------- attendance today ----------
    today_att = frappe.get_all(
        "Attendance",
        filters={"company": company, "attendance_date": day, "docstatus": 1},
        fields=["employee", "employee_name", "status", "leave_type"],
    )
    status_count = {}
    for a in today_att:
        status_count[a.status] = status_count.get(a.status, 0) + 1
    marked_active = len({a.employee for a in today_att if a.employee in active_names})
    present = status_count.get("Present", 0) + status_count.get("Work From Home", 0) + status_count.get("Half Day", 0)

    # ---------- missing punches today ----------
    missing_punches = frappe.db.sql(
        """select c.employee, e.employee_name, min(c.time) as time
           from `tabEmployee Checkin` c
           inner join `tabEmployee` e on e.name = c.employee
           where e.company = %s and e.status = 'Active' and c.time between %s and %s
           group by c.employee, e.employee_name
           having count(*) = 1
           order by e.employee_name""",
        (company, f"{day} 00:00:00", f"{day} 23:59:59"),
        as_dict=True,
    )

    # ---------- joiners / leavers ----------
    joiners_month = [e for e in employees if e.date_of_joining and start <= getdate(e.date_of_joining) <= end]
    leavers_month = [e for e in employees if e.relieving_date and start <= getdate(e.relieving_date) <= end]

    # ---------- salary ----------
    salaries = {}
    if show_salary:
        from hr_toolkit.hr_toolkit.report.employee_list.employee_list import get_current_salaries
        salaries = get_current_salaries()
    payroll = sum(flt(salaries.get(e.name)) for e in active)

    # ---------- salary slips this month ----------
    slips = frappe.get_all(
        "Salary Slip",
        filters={"company": company, "start_date": [">=", start], "end_date": ["<=", end], "docstatus": ["<", 2]},
        fields=["docstatus", "net_pay"],
    )
    slips_submitted = [s for s in slips if s.docstatus == 1]

    # ---------- overtime this month ----------
    overtime_rows = frappe.db.sql(
        """select emp.department, sum(d.overtime_hours) as hours, sum(d.overtime_amount) as amount
           from `tabOvertime Entry Detail` d
           inner join `tabOvertime Entry` e on e.name = d.parent
           left join `tabEmployee` emp on emp.name = d.employee
           where e.docstatus = 1 and e.company = %s and e.overtime_date between %s and %s
           group by emp.department""",
        (company, start, end),
        as_dict=True,
    )
    ot_hours = sum(flt(r.hours) for r in overtime_rows)
    ot_amount = sum(flt(r.amount) for r in overtime_rows)

    # ---------- missing information ----------
    missing_info = 0
    try:
        from hr_toolkit.hr_toolkit.report.employee_list.employee_list import execute as employee_list
        missing_info = len(employee_list({"company": company, "status": "Active", "only_missing": 1})[1])
    except Exception:
        missing_info = 0

    # ---------- cards ----------
    cards = [
        {"label": _("Active Employees"), "value": len(active), "type": "Int", "color": "#2490ef",
         "sub": _("{0} total").format(len(employees)),
         "route": ["List", "Employee", {"company": company, "status": "Active"}]},
        {"label": _("New Joiners"), "value": len(joiners_month), "type": "Int", "color": "#28a745",
         "sub": data.month_label,
         "route": ["List", "Employee", {"company": company, "date_of_joining": ["between", [str(start), str(end)]]}]},
        {"label": _("Left"), "value": len(leavers_month), "type": "Int", "color": "#e24c4c",
         "sub": data.month_label,
         "route": ["List", "Employee", {"company": company, "relieving_date": ["between", [str(start), str(end)]]}]},
        {"label": _("Present Today"), "value": present, "type": "Int", "color": "#28a745",
         "sub": _("{0}% of active").format(round(present * 100 / len(active)) if active else 0),
         "route": ["List", "Attendance", {"company": company, "attendance_date": str(day), "status": "Present", "docstatus": 1}]},
        {"label": _("Absent Today"), "value": status_count.get("Absent", 0), "type": "Int", "color": "#e24c4c",
         "sub": str(day),
         "route": ["List", "Attendance", {"company": company, "attendance_date": str(day), "status": "Absent", "docstatus": 1}]},
        {"label": _("On Leave Today"), "value": status_count.get("On Leave", 0), "type": "Int", "color": "#7c5cff",
         "sub": str(day),
         "route": ["List", "Attendance", {"company": company, "attendance_date": str(day), "status": "On Leave", "docstatus": 1}]},
        {"label": _("Not Marked Today"), "value": max(len(active) - marked_active, 0), "type": "Int", "color": "#8d99a6",
         "sub": _("No attendance yet"), "route": ["List", "Attendance", {"company": company, "attendance_date": str(day)}]},
        {"label": _("Missing Punches Today"), "value": len(missing_punches), "type": "Int", "color": "#f39c12",
         "sub": _("Single checkin only"), "route": ["Form", "Checkin Adjustment Tool"]},
        {"label": _("Overtime Hours"), "value": ot_hours, "type": "Float", "color": "#17a2b8",
         "sub": data.month_label, "route": ["List", "Overtime Entry", {"company": company, "docstatus": 1}]},
        {"label": _("Salary Slips"), "value": len(slips_submitted), "type": "Int", "color": "#2490ef",
         "sub": _("{0} draft").format(len(slips) - len(slips_submitted)),
         "route": ["List", "Salary Slip", {"company": company, "start_date": [">=", str(start)]}]},
        {"label": _("Missing Information"), "value": missing_info, "type": "Int",
         "color": "#f39c12" if missing_info else "#28a745", "sub": _("Active employees"),
         "route": ["query-report", "Employee List", {"company": company, "only_missing": 1}]},
    ]
    if show_salary:
        cards.insert(8, {"label": _("Monthly Payroll"), "value": payroll, "type": "Currency", "color": "#2490ef",
                         "sub": _("Active employees"), "route": ["query-report", "Employee List", {"company": company}]})
        cards.insert(10, {"label": _("Overtime Amount"), "value": ot_amount, "type": "Currency", "color": "#17a2b8",
                          "sub": data.month_label, "route": ["List", "Overtime Entry", {"company": company, "docstatus": 1}]})
        cards.insert(12, {"label": _("Net Pay (Submitted)"), "value": sum(flt(s.net_pay) for s in slips_submitted),
                          "type": "Currency", "color": "#28a745", "sub": data.month_label,
                          "route": ["List", "Salary Slip", {"company": company, "docstatus": 1, "start_date": [">=", str(start)]}]})
    data.cards = cards

    # ---------- charts ----------
    charts = {}

    trend_start = add_days(day, -29)
    trend = frappe.db.sql(
        """select attendance_date as d, status, count(*) as c from `tabAttendance`
           where docstatus = 1 and company = %s and attendance_date between %s and %s
           group by attendance_date, status""",
        (company, trend_start, day),
        as_dict=True,
    )
    labels, p, a, l = [], [], [], []
    by_day = {}
    for t in trend:
        by_day.setdefault(str(t.d), {})[t.status] = t.c
    for i in range(30):
        d = getdate(add_days(trend_start, i))
        s = by_day.get(str(d), {})
        labels.append(d.strftime("%d-%m"))
        p.append(s.get("Present", 0) + s.get("Work From Home", 0) + s.get("Half Day", 0))
        a.append(s.get("Absent", 0))
        l.append(s.get("On Leave", 0))
    charts["attendance"] = {"labels": labels, "datasets": [
        {"name": _("Present"), "values": p}, {"name": _("Absent"), "values": a}, {"name": _("On Leave"), "values": l}]}

    dept = {}
    for e in active:
        k = _short(e.department)
        dept[k] = dept.get(k, 0) + 1
    dept_labels = sorted(dept, key=lambda k: -dept[k])
    charts["department"] = {"labels": dept_labels, "datasets": [{"name": _("Employees"), "values": [dept[k] for k in dept_labels]}]}

    gender = {}
    for e in active:
        k = e.gender or _("Not Set")
        gender[k] = gender.get(k, 0) + 1
    charts["gender"] = {"labels": list(gender), "datasets": [{"name": _("Employees"), "values": list(gender.values())}]}

    month_labels, joined, left = [], [], []
    for i in range(11, -1, -1):
        m_start = getdate(get_first_day(add_months(day, -i)))
        m_end = getdate(get_last_day(m_start))
        month_labels.append(m_start.strftime("%b %y"))
        joined.append(len([e for e in employees if e.date_of_joining and m_start <= getdate(e.date_of_joining) <= m_end]))
        left.append(len([e for e in employees if e.relieving_date and m_start <= getdate(e.relieving_date) <= m_end]))
    charts["joiners"] = {"labels": month_labels, "datasets": [
        {"name": _("Joined"), "values": joined}, {"name": _("Left"), "values": left}]}

    if show_salary:
        band_counts = []
        for low, high, _label in SALARY_BANDS:
            band_counts.append(len([e for e in active if flt(salaries.get(e.name)) >= low
                                    and (high is None or flt(salaries.get(e.name)) < high)]))
        charts["salary_bands"] = {"labels": [b[2] for b in SALARY_BANDS],
                                  "datasets": [{"name": _("Employees"), "values": band_counts}]}

    ot_labels = [_short(r.department) for r in overtime_rows]
    charts["overtime"] = {"labels": ot_labels, "datasets": [
        {"name": _("Amount") if show_salary else _("Hours"),
         "values": [flt(r.amount if show_salary else r.hours, 2) for r in overtime_rows]}]}
    data.charts = charts

    # ---------- lists ----------
    def count(doctype, filters):
        return frappe.db.count(doctype, filters) if frappe.db.exists("DocType", doctype) else 0

    data.pending = [
        {"label": _("Leave Applications"), "count": count("Leave Application", {"company": company, "status": "Open", "docstatus": 0}),
         "route": ["List", "Leave Application", {"company": company, "status": "Open", "docstatus": 0}]},
        {"label": _("Overtime Entry"), "count": count("Overtime Entry", {"company": company, "docstatus": 0}),
         "route": ["List", "Overtime Entry", {"company": company, "docstatus": 0}]},
        {"label": _("Bonus Entry"), "count": count("Bonus Entry", {"company": company, "docstatus": 0}),
         "route": ["List", "Bonus Entry", {"company": company, "docstatus": 0}]},
        {"label": _("Salary Revision"), "count": count("Salary Revision", {"company": company, "docstatus": 0}),
         "route": ["List", "Salary Revision", {"company": company, "docstatus": 0}]},
        {"label": _("Draft Salary Slips"), "count": len(slips) - len(slips_submitted),
         "route": ["List", "Salary Slip", {"company": company, "docstatus": 0}]},
    ]

    birthdays = []
    for e in active:
        if not e.date_of_birth:
            continue
        dob = getdate(e.date_of_birth)
        for k in range(8):
            d = getdate(add_days(day, k))
            if d.month == dob.month and d.day == dob.day:
                birthdays.append({"employee": e.name, "name": e.employee_name, "date": str(d),
                                  "in_days": k, "age": d.year - dob.year})
                break
    data.birthdays = sorted(birthdays, key=lambda x: x["in_days"])

    anniversaries = []
    for e in active:
        if e.date_of_joining:
            doj = getdate(e.date_of_joining)
            if doj.month == day.month and doj.year < day.year:
                anniversaries.append({"employee": e.name, "name": e.employee_name,
                                      "date": f"{doj.day:02d}-{doj.month:02d}", "years": day.year - doj.year})
    data.anniversaries = sorted(anniversaries, key=lambda x: x["date"])

    data.on_leave = [{"employee": a.employee, "name": a.employee_name, "leave_type": a.leave_type or ""}
                     for a in today_att if a.status == "On Leave"]

    data.missing_punches = [{"employee": m.employee, "name": m.employee_name,
                             "time": getdate(m.time) and str(m.time)[11:16]} for m in missing_punches[:20]]

    data.recent_joiners = [{"employee": e.name, "name": e.employee_name, "department": _short(e.department),
                            "date": str(e.date_of_joining)}
                           for e in sorted([x for x in active if x.date_of_joining],
                                           key=lambda x: getdate(x.date_of_joining), reverse=True)[:8]]

    policy = frappe.db.get_value("Bonus Policy", {"company": company, "enabled": 1},
                                 ["name", "min_service_months"], as_dict=True) \
        if frappe.db.exists("DocType", "Bonus Policy") else None
    min_months = cint(policy.min_service_months) if policy else 6
    bonus_soon = []
    for e in active:
        if e.date_of_joining:
            due = getdate(add_months(e.date_of_joining, min_months))
            if day <= due <= getdate(add_days(day, 30)):
                bonus_soon.append({"employee": e.name, "name": e.employee_name, "date": str(due)})
    data.bonus_soon = sorted(bonus_soon, key=lambda x: x["date"])
    data.bonus_months = min_months

    return data
