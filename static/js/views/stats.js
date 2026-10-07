import * as api from "../api.js";
import { t, nameOf as langOf } from "../i18n.js";
import { esc, qs, qsa, fmtDate, fmtDateTime } from "../ui.js";
import { state, can, navigate } from "../app.js";

const filters = {
  from: "", to: "", group: "day", user_id: "", status_key: "", work_type: "",
};

export async function renderStats(container) {
  if (!can("stats.view")) {
    container.innerHTML = `<div class="page"><div class="alert alert-danger">${esc(t("forbidden"))}</div></div>`;
    return;
  }
  container.innerHTML = `
    <div class="page">
      <div class="page-head">
        <h1>${esc(t("stats_title"))}</h1>
        <div class="spacer"></div>
        ${can("stats.export") ? `
          <a class="btn btn-sm" id="exp-csv" href="#">${esc(t("export_csv"))}</a>
          <a class="btn btn-sm" id="exp-xlsx" href="#">${esc(t("export_xlsx"))}</a>` : ""}
      </div>

      <div class="filters-panel" style="display:grid">
        <div class="field"><label>${esc(t("from"))}</label><input class="input" type="date" id="st-from" value="${esc(filters.from)}"></div>
        <div class="field"><label>${esc(t("to"))}</label><input class="input" type="date" id="st-to" value="${esc(filters.to)}"></div>
        <div class="field"><label>${esc(t("group"))}</label>
          <select class="select" id="st-group">
            <option value="day" ${filters.group === "day" ? "selected" : ""}>${esc(t("g_day"))}</option>
            <option value="week" ${filters.group === "week" ? "selected" : ""}>${esc(t("g_week"))}</option>
            <option value="month" ${filters.group === "month" ? "selected" : ""}>${esc(t("g_month"))}</option>
          </select></div>
        <div class="field"><label>${esc(t("f_status"))}</label>
          <select class="select" id="st-status">
            <option value="">${esc(t("f_any"))}</option>
            ${state.meta.statuses.map((s) => `<option value="${esc(s.key)}" ${filters.status_key === s.key ? "selected" : ""}>${esc(langOf(s))}</option>`).join("")}
          </select></div>
        <div class="field"><label>${esc(t("f_work_type"))}</label>
          <select class="select" id="st-wt">
            <option value="">${esc(t("type_all"))}</option>
            ${state.meta.work_types.map((w) => `<option value="${w.id}" ${filters.work_type == w.id ? "selected" : ""}>${esc(langOf(w))}</option>`).join("")}
          </select></div>
        ${can("stats.all") ? `
        <div class="field"><label>${esc(t("f_responsible"))}</label>
          <select class="select" id="st-user">
            <option value="">${esc(t("emp_all"))}</option>
            ${state.meta.users.map((u) => `<option value="${u.id}" ${filters.user_id == u.id ? "selected" : ""}>${esc(u.full_name || u.login)}</option>`).join("")}
          </select></div>` : ""}
        <div class="field"><label>&nbsp;</label><button class="btn" id="st-reset">${esc(t("reset_filters"))}</button></div>
      </div>

      <div id="st-body"><div class="hint">${esc(t("loading"))}</div></div>
    </div>`;

  qs("#st-from").onchange = (e) => { filters.from = e.target.value; load(); };
  qs("#st-to").onchange = (e) => { filters.to = e.target.value; load(); };
  qs("#st-group").onchange = (e) => { filters.group = e.target.value; load(); };
  qs("#st-status").onchange = (e) => { filters.status_key = e.target.value; load(); };
  qs("#st-wt").onchange = (e) => { filters.work_type = e.target.value; load(); };
  const userSel = qs("#st-user");
  if (userSel) userSel.onchange = (e) => { filters.user_id = e.target.value; load(); };
  qs("#st-reset").onclick = () => {
    Object.assign(filters, { from: "", to: "", group: "day", user_id: "", status_key: "", work_type: "" });
    renderStats(container);
  };

  updateExportLinks();
  await load();
}

function params() {
  return api.qs({
    from: filters.from ? filters.from + "T00:00:00.000Z" : "",
    to: filters.to ? filters.to + "T23:59:59.999Z" : "",
    group: filters.group,
    status_key: filters.status_key,
    work_type: filters.work_type,
    user_id: filters.user_id,
  });
}

function updateExportLinks() {
  const csv = qs("#exp-csv");
  const xlsx = qs("#exp-xlsx");
  if (csv) csv.href = "/api/stats/export" + api.qs({ ...paramsObj(), format: "csv" });
  if (xlsx) xlsx.href = "/api/stats/export" + api.qs({ ...paramsObj(), format: "xlsx" });
}

function paramsObj() {
  return {
    from: filters.from ? filters.from + "T00:00:00.000Z" : "",
    to: filters.to ? filters.to + "T23:59:59.999Z" : "",
    group: filters.group,
    status_key: filters.status_key,
    work_type: filters.work_type,
    user_id: filters.user_id,
  };
}

async function load() {
  const body = qs("#st-body");
  if (!body) return;
  const data = await api.get("/api/stats" + params());
  body.innerHTML = render(data);
  qsa("[data-open]", body).forEach((b) => (b.onclick = () => navigate("#/order/" + b.dataset.open)));
}

function bars(entries, empty) {
  const items = Object.entries(entries || {});
  if (!items.length) return `<div class="hint">${esc(empty)}</div>`;
  const max = Math.max(...items.map(([, v]) => v), 1);
  return `<table class="tbl"><tbody>
    ${items.map(([k, v]) => `
      <tr><td style="width:45%">${esc(k)}</td>
        <td><div class="progress" style="margin:0"><span style="width:${Math.round((v / max) * 100)}%"></span></div></td>
        <td style="width:50px;text-align:right"><b>${v}</b></td></tr>`).join("")}
  </tbody></table>`;
}

function render(d) {
  const dyn = d.dynamics || [];
  const maxDyn = Math.max(...dyn.map((x) => x.count), 1);

  return `
    <div class="grid-4">
      <div class="stat-card"><div class="s-label">${esc(t("s_completed"))}</div><div class="s-value">${d.completed}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("s_active"))}</div><div class="s-value">${d.active}</div></div>
      <div class="stat-card ${d.overdue ? "danger" : ""}"><div class="s-label">${esc(t("s_overdue"))}</div><div class="s-value">${d.overdue}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("period"))}</div><div class="s-value" style="font-size:18px">${d.total_orders}</div>
        <div class="s-sub">${esc(t("orders_count"))}</div></div>
    </div>
    <div class="grid-3" style="margin-top:14px">
      <div class="stat-card"><div class="s-label">${esc(t("s_avg"))}</div><div class="s-value" style="font-size:22px">${esc(d.avg_intake_to_ready)}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("s_wait"))}</div><div class="s-value" style="font-size:22px">${esc(d.waiting)}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("s_overdue"))}</div>
        <div class="s-value" style="font-size:22px;${d.overdue ? "color:var(--danger)" : ""}">${d.overdue}</div></div>
    </div>

    <div class="panel" style="margin-top:14px">
      <h3>${esc(t("s_dynamics"))} (${esc(t("g_" + filters.group))})</h3>
      ${dyn.length ? `
        <div class="chart">
          ${dyn.map((x) => `<div class="bar" style="height:${Math.max(3, Math.round((x.count / maxDyn) * 100))}%" title="${esc(x.label)}: ${x.count}"><span>${x.count}</span></div>`).join("")}
        </div>
        <div class="chart-labels">${dyn.map((x) => `<div>${esc(x.label)}</div>`).join("")}</div>`
      : `<div class="hint">${esc(t("no_data"))}</div>`}
    </div>

    <div class="grid-2" style="margin-top:14px">
      <div class="panel">
        <h3>${esc(t("s_load"))}</h3>
        ${bars(d.load_by_employee, t("no_data"))}
      </div>
      <div class="panel">
        <h3>${esc(t("s_by_emp"))}</h3>
        ${bars(d.orders_by_employee, t("no_data"))}
      </div>
      <div class="panel">
        <h3>${esc(t("s_by_type"))}</h3>
        ${bars(d.by_work_type, t("no_data"))}
      </div>
      <div class="panel">
        <h3>${esc(t("s_stages"))}</h3>
        ${Object.keys(d.avg_stage || {}).length ? `
          <table class="tbl"><thead><tr><th>${esc(t("f_status"))}</th><th>${esc(t("duration"))}</th></tr></thead><tbody>
            ${Object.entries(d.avg_stage).map(([k, v]) => {
              const st = state.meta.statuses.find((s) => s.key === k);
              return `<tr><td>${esc(st ? langOf(st) : k)}</td><td>${esc(v)}</td></tr>`;
            }).join("")}
          </tbody></table>` : `<div class="hint">${esc(t("no_data"))}</div>`}
      </div>
    </div>

    ${(d.overdue_orders || []).length ? `
    <div class="panel" style="margin-top:14px">
      <h3>${esc(t("s_overdue_list"))}</h3>
      <table class="tbl">
        <thead><tr><th>${esc(t("order"))}</th><th>${esc(t("plate"))}</th><th>${esc(t("due_at"))}</th><th></th></tr></thead>
        <tbody>
          ${d.overdue_orders.map((o) => `
            <tr>
              <td><b>${esc(o.number)}</b></td>
              <td>${esc(o.plate || "—")}</td>
              <td style="color:var(--danger)">${esc(fmtDateTime(o.due_at))}</td>
              <td><button class="btn btn-sm" data-open="${o.id}">${esc(t("open_order"))}</button></td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>` : ""}`;
}
