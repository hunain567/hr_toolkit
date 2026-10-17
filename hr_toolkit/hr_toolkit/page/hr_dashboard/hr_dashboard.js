frappe.pages["hr-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("HR Dashboard"),
        single_column: true,
    });
    wrapper.hr_dashboard = new HRDashboard(page);
};

frappe.pages["hr-dashboard"].on_page_show = function (wrapper) {
    if (wrapper.hr_dashboard) {
        wrapper.hr_dashboard.refresh();
    }
};

class HRDashboard {
    constructor(page) {
        this.page = page;
        this.add_style();
        this.make_filters();
        this.$body = $('<div class="hrd"></div>').appendTo(page.main);
    }

    make_filters() {
        this.company = this.page.add_field({
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            change: () => this.refresh(),
        });
        this.date = this.page.add_field({
            fieldname: "date",
            label: __("Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            change: () => this.refresh(),
        });
        this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
    }

    refresh() {
        if (this.loading) return;
        this.loading = true;
        frappe.call({
            method: "hr_toolkit.hr_toolkit.page.hr_dashboard.hr_dashboard.get_dashboard_data",
            args: { company: this.company.get_value(), date: this.date.get_value() },
            callback: (r) => {
                this.loading = false;
                if (r.message) this.render(r.message);
            },
            error: () => {
                this.loading = false;
            },
        });
    }

    fmt(value, type, currency) {
        if (type === "Currency") return format_currency(value || 0, currency, 0);
        if (type === "Float") return format_number(value || 0, null, 1);
        return format_number(value || 0, null, 0);
    }

    render(d) {
        this.data = d;
        const esc = frappe.utils.escape_html;

        const cards = (d.cards || []).map((c, i) => `
            <div class="hrd-card" data-index="${i}" style="--hrd-accent: ${c.color}">
                <div class="hrd-card-label">${esc(c.label)}</div>
                <div class="hrd-card-value">${this.fmt(c.value, c.type, d.currency)}</div>
                <div class="hrd-card-sub">${esc(c.sub || "")}</div>
            </div>`).join("");

        const chart_panel = (key, title) => d.charts[key] ? `
            <div class="hrd-panel">
                <div class="hrd-panel-title">${esc(title)}</div>
                <div class="hrd-chart" data-chart="${key}"></div>
            </div>` : "";

        this.$body.html(`
            <div class="hrd-section-title">${__("Overview")} <span class="hrd-muted">· ${esc(d.company)} · ${esc(d.month_label)}</span></div>
            <div class="hrd-cards">${cards}</div>

            <div class="hrd-section-title">${__("Trends")}</div>
            <div class="hrd-grid-2">
                ${chart_panel("attendance", __("Attendance Trend (30 Days)"))}
                ${chart_panel("department", __("Headcount by Department"))}
                ${chart_panel("joiners", __("Joiners vs Leavers (12 Months)"))}
                ${chart_panel("gender", __("Gender Split"))}
                ${chart_panel("salary_bands", __("Salary Bands"))}
                ${chart_panel("overtime", d.show_salary ? __("Overtime Amount by Department") : __("Overtime Hours by Department"))}
            </div>

            <div class="hrd-section-title">${__("Action Items")}</div>
            <div class="hrd-grid-3">
                ${this.pending_panel(d)}
                ${this.list_panel(__("Missing Punches Today"), d.missing_punches, (x) => [x.name, x.time])}
                ${this.list_panel(__("On Leave Today"), d.on_leave, (x) => [x.name, x.leave_type])}
                ${this.list_panel(__("Bonus Eligible in 30 Days"), d.bonus_soon, (x) => [x.name, frappe.datetime.str_to_user(x.date)],
                    __("{0} months service", [d.bonus_months]))}
            </div>

            <div class="hrd-section-title">${__("People")}</div>
            <div class="hrd-grid-3">
                ${this.list_panel(__("Birthdays (Next 7 Days)"), d.birthdays,
                    (x) => [x.name, x.in_days === 0 ? __("Today") + " 🎂" : frappe.datetime.str_to_user(x.date)])}
                ${this.list_panel(__("Work Anniversaries This Month"), d.anniversaries,
                    (x) => [x.name, __("{0} years · {1}", [x.years, x.date])])}
                ${this.list_panel(__("Recent Joiners"), d.recent_joiners,
                    (x) => [x.name, `${esc(x.department)} · ${frappe.datetime.str_to_user(x.date)}`])}
            </div>
        `);

        this.$body.find(".hrd-card").on("click", (e) => {
            const card = d.cards[$(e.currentTarget).data("index")];
            if (card && card.route) frappe.set_route(...card.route);
        });
        this.$body.find("[data-route]").on("click", (e) => {
            const route = JSON.parse(decodeURIComponent($(e.currentTarget).attr("data-route")));
            frappe.set_route(...route);
        });
        this.$body.find("[data-employee]").on("click", (e) => {
            frappe.set_route("Form", "Employee", $(e.currentTarget).attr("data-employee"));
        });

        this.render_charts(d);
    }

    pending_panel(d) {
        const rows = (d.pending || []).map((p) => `
            <div class="hrd-list-item hrd-link" data-route="${encodeURIComponent(JSON.stringify(p.route))}">
                <span>${frappe.utils.escape_html(p.label)}</span>
                <span class="hrd-badge ${p.count ? "hrd-badge-warn" : ""}">${p.count}</span>
            </div>`).join("");
        return `<div class="hrd-panel"><div class="hrd-panel-title">${__("Pending Approvals")}</div>${rows}</div>`;
    }

    list_panel(title, items, row_fn, subtitle) {
        const esc = frappe.utils.escape_html;
        const body = (items || []).length
            ? items.map((x) => {
                const [left, right] = row_fn(x);
                return `<div class="hrd-list-item hrd-link" data-employee="${esc(x.employee)}">
                            <span>${esc(left || "")}</span><span class="hrd-muted">${right || ""}</span>
                        </div>`;
            }).join("")
            : `<div class="hrd-empty">${__("Nothing to show")}</div>`;
        return `<div class="hrd-panel">
                    <div class="hrd-panel-title">${esc(title)}
                        <span class="hrd-muted">${subtitle ? esc(subtitle) : (items || []).length}</span>
                    </div>${body}</div>`;
    }

    render_charts(d) {
        const settings = {
            attendance: { type: "line", colors: ["#28a745", "#e24c4c", "#7c5cff"],
                lineOptions: { regionFill: 1, hideDots: 1 }, axisOptions: { xIsSeries: 1, xAxisMode: "tick" } },
            department: { type: "bar", colors: ["#2490ef"] },
            joiners: { type: "bar", colors: ["#28a745", "#e24c4c"] },
            gender: { type: "donut", colors: ["#2490ef", "#ff6b9d", "#8d99a6"] },
            salary_bands: { type: "bar", colors: ["#7c5cff"] },
            overtime: { type: "bar", colors: ["#17a2b8"] },
        };
        this.$body.find(".hrd-chart").each((_, el) => {
            const key = $(el).data("chart");
            const chart = d.charts[key];
            if (!chart || !(chart.labels || []).length) {
                $(el).html(`<div class="hrd-empty">${__("No data")}</div>`);
                return;
            }
            new frappe.Chart(el, Object.assign({ data: chart, height: 260 }, settings[key]));
        });
    }

    add_style() {
        if (document.getElementById("hrd-style")) return;
        const style = document.createElement("style");
        style.id = "hrd-style";
        style.textContent = `
            .hrd { padding: 4px 0 32px; }
            .hrd-section-title { font-weight: 600; font-size: var(--text-lg); margin: 24px 0 12px; color: var(--heading-color); }
            .hrd-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
            .hrd-card { background: var(--card-bg); border: 1px solid var(--border-color); border-left: 4px solid var(--hrd-accent);
                border-radius: var(--border-radius-lg); padding: 14px 16px; cursor: pointer; transition: box-shadow .15s, transform .15s; }
            .hrd-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
            .hrd-card-label { color: var(--text-muted); font-size: var(--text-sm); }
            .hrd-card-value { font-size: 24px; font-weight: 700; margin-top: 4px; color: var(--heading-color); white-space: nowrap; }
            .hrd-card-sub { color: var(--text-muted); font-size: var(--text-xs); margin-top: 2px; }
            .hrd-grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(440px, 100%), 1fr)); gap: 12px; }
            .hrd-grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); gap: 12px; }
            .hrd-panel { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-lg);
                padding: 14px 16px; min-height: 140px; }
            .hrd-panel-title { font-weight: 600; margin-bottom: 8px; display: flex; justify-content: space-between; gap: 8px; }
            .hrd-list-item { display: flex; justify-content: space-between; gap: 8px; padding: 7px 0;
                border-bottom: 1px dashed var(--border-color); font-size: var(--text-sm); }
            .hrd-list-item:last-child { border-bottom: none; }
            .hrd-link { cursor: pointer; }
            .hrd-link:hover span:first-child { color: var(--primary); }
            .hrd-muted { color: var(--text-muted); font-weight: 400; }
            .hrd-empty { color: var(--text-muted); font-size: var(--text-sm); padding: 16px 0; }
            .hrd-badge { min-width: 28px; text-align: center; padding: 0 8px; border-radius: 10px;
                background: var(--control-bg); font-weight: 600; }
            .hrd-badge-warn { background: var(--bg-orange, #fff1e0); color: var(--text-on-orange, #b25e00); }
        `;
        document.head.appendChild(style);
    }
}
