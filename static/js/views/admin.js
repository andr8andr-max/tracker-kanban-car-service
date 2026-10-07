import * as api from "../api.js";
import { t, nameOf, getLang } from "../i18n.js";
import {
  esc, qs, qsa, toast, openModal, closeModal, confirmDialog,
  fmtDateTime, fmtDate, copyText, debounce,
} from "../ui.js";
import { state, can, navigate, langOf } from "../app.js";

const TABS = [
  ["users", "admin_users", "users.manage"],
  ["roles", "admin_roles", "roles.manage"],
  ["statuses", "admin_statuses", "board.manage"],
  ["worktypes", "admin_worktypes", "worktypes.manage"],
  ["checklists", "admin_checklists", "checklists.manage"],
  ["templates", "admin_templates", "templates.manage"],
  ["settings", "admin_settings", "settings.manage"],
  ["telegram", "telegram_settings", "telegram.manage"],
  ["backup", "admin_backup", "backup.manage"],
  ["audit", "admin_audit", "audit.view"],
  ["trash", "admin_trash", "order.restore"],
];

let current = "users";

export async function renderAdmin(container, [tab]) {
  const allowed = TABS.filter(([, , perm]) => can(perm));
  if (!allowed.length) {
    container.innerHTML = `<div class="page"><div class="alert alert-danger">${esc(t("forbidden"))}</div></div>`;
    return;
  }
  current = tab && allowed.some(([k]) => k === tab) ? tab : allowed[0][0];

  container.innerHTML = `
    <div class="page">
      <div class="page-head"><h1>${esc(t("nav_admin"))}</h1></div>
      <div class="tabs" id="adm-tabs">
        ${allowed.map(([key, label]) => `<button class="tab ${key === current ? "active" : ""}" data-tab="${key}">${esc(t(label))}</button>`).join("")}
      </div>
      <div id="adm-body"><div class="hint">${esc(t("loading"))}</div></div>
    </div>`;

  qsa("#adm-tabs .tab").forEach((b) => (b.onclick = () => navigate("#/admin/" + b.dataset.tab)));

  const renderers = {
    users: tabUsers, roles: tabRoles, statuses: tabStatuses, worktypes: tabWorktypes,
    checklists: tabChecklists, templates: tabTemplates, settings: tabSettings,
    telegram: tabTelegram, backup: tabBackup, audit: tabAudit, trash: tabTrash,
  };
  await renderers[current](qs("#adm-body"));
}

const rerender = () => renderAdmin(qs("#view"), [current]);

/* ================================================================ users */
async function tabUsers(host) {
  const [usersData] = await Promise.all([api.get("/api/admin/users")]);
  const users = usersData.users;
  const roles = state.meta.roles;

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_users"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="u-add">${esc(t("create_user"))}</button></span>
      </h3>
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("login"))}</th><th>${esc(t("full_name"))}</th><th>${esc(t("role_col"))}</th>
          <th>${esc(t("language"))}</th><th>${esc(t("active"))}</th><th>${esc(t("last_login"))}</th><th></th>
        </tr></thead>
        <tbody>
          ${users.map((u) => `
            <tr data-id="${u.id}">
              <td><b>${esc(u.login)}</b>${u.must_change_password ? ` <span class="badge badge-amber">${esc(t("temp_password"))}</span>` : ""}</td>
              <td>${esc(u.full_name || "")}</td>
              <td>
                <select class="select u-role" data-id="${u.id}" style="width:auto;padding:4px 8px">
                  <option value="">—</option>
                  ${roles.map((r) => `<option value="${r.id}" ${u.role_id === r.id ? "selected" : ""}>${esc(langOf(r))}</option>`).join("")}
                </select>
              </td>
              <td>${esc(u.lang || "ru")}</td>
              <td>${u.active && u.role_id
                  ? `<span class="badge badge-green">${esc(t("active"))}</span>`
                  : `<span class="badge badge-red">${esc(t("blocked"))}</span>`}</td>
              <td>${esc(u.last_login_at ? fmtDateTime(u.last_login_at) : "—")}</td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn btn-sm u-reset" data-id="${u.id}">${esc(t("reset_password"))}</button>
                <button class="btn btn-sm u-toggle" data-id="${u.id}">${u.active ? esc(t("block")) : esc(t("unblock"))}</button>
                <button class="btn btn-sm btn-danger u-del" data-id="${u.id}">${esc(t("delete"))}</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  qs("#u-add").onclick = () => userModal(null, rerender);

  qsa(".u-role", host).forEach((sel) => (sel.onchange = async () => {
    try {
      await api.put(`/api/admin/users/${sel.dataset.id}`, {
        role_id: sel.value ? parseInt(sel.value, 10) : null,
      });
      toast(t("saved"), "success");
      rerender();
    } catch (e) { toast(e.message, "error"); }
  }));

  qsa(".u-reset", host).forEach((b) => (b.onclick = () => resetPasswordModal(b.dataset.id, rerender)));

  qsa(".u-toggle", host).forEach((b) => (b.onclick = async () => {
    const row = b.closest("tr");
    const active = b.textContent === t("block");
    try {
      await api.put(`/api/admin/users/${b.dataset.id}`, { active: !active });
      toast(t("saved"), "success");
      rerender();
    } catch (e) { toast(e.message, "error"); }
  }));

  qsa(".u-del", host).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    try {
      await api.del(`/api/admin/users/${b.dataset.id}`);
      toast(t("saved"), "success");
      rerender();
    } catch (e) { toast(e.message, "error"); }
  }));
}

function userModal(user, onDone) {
  const isNew = !user;
  const defLang = (state.user && state.user.settings && state.user.settings.default_lang) || "ru";
  const effLang = isNew ? defLang : (user.lang_custom ? user.lang : defLang);
  const wrap = openModal({
    title: isNew ? t("create_user") : user.login,
    body: `
      <div class="form-row">
        <div class="field"><label>${esc(t("login"))} <span class="req">*</span></label>
          <input class="input" id="um-login" value="${esc(user ? user.login : "")}" ${isNew ? "" : "disabled"}></div>
        <div class="field"><label>${esc(t("full_name"))}</label>
          <input class="input" id="um-name" value="${esc(user ? user.full_name || "" : "")}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("role_col"))}</label>
          <select class="select" id="um-role">
            <option value="">—</option>
            ${state.meta.roles.map((r) => `<option value="${r.id}" ${user && user.role_id === r.id ? "selected" : ""}>${esc(langOf(r))}</option>`).join("")}
          </select></div>
        <div class="field"><label>${esc(t("language"))}</label>
          <select class="select" id="um-lang">
            <option value="ru" ${effLang === "ru" ? "selected" : ""}>RU</option>
            <option value="en" ${effLang === "en" ? "selected" : ""}>EN</option>
          </select></div>
      </div>
      <div class="field"><label>${isNew ? esc(t("temp_password")) : esc(t("new_password"))}</label>
        <input class="input" id="um-pass" type="text" value="changeme"></div>
      <div class="hint">${esc(t("password_min"))}</div>
      <div class="error-text" id="um-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="um-save">${esc(t("save"))}</button>`,
  });
  qs("#um-save", wrap).onclick = async () => {
    const payload = {
      login: qs("#um-login", wrap).value.trim(),
      full_name: qs("#um-name", wrap).value.trim(),
      role_id: qs("#um-role", wrap).value ? parseInt(qs("#um-role", wrap).value, 10) : null,
      lang: qs("#um-lang", wrap).value,
      password: qs("#um-pass", wrap).value,
    };
    try {
      if (isNew) await api.post("/api/admin/users", payload);
      else await api.put(`/api/admin/users/${user.id}`, {
        full_name: payload.full_name, role_id: payload.role_id, lang: payload.lang,
        reset_password: !!payload.password, password: payload.password,
      });
      closeModal();
      toast(t("user_saved"), "success");
      onDone();
    } catch (e) { qs("#um-err", wrap).textContent = e.message || t("error"); }
  };
}

function resetPasswordModal(userId, onDone) {
  const wrap = openModal({
    title: t("reset_password"),
    size: "sm",
    body: `<div class="field"><label>${esc(t("new_password"))}</label>
             <input class="input" id="rp-pass" type="text" value="changeme"></div>
           <div class="hint">${esc(t("password_min"))}</div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="rp-go">${esc(t("save"))}</button>`,
  });
  qs("#rp-go", wrap).onclick = async () => {
    const pass = qs("#rp-pass", wrap).value;
    if (pass.length < 6) { toast(t("password_min"), "error"); return; }
    try {
      await api.put(`/api/admin/users/${userId}`, { reset_password: true, password: pass });
      closeModal();
      toast(t("saved"), "success");
      onDone();
    } catch (e) { toast(e.message, "error"); }
  };
}

/* ================================================================ roles */
async function tabRoles(host) {
  const data = await api.get("/api/admin/roles");
  const roles = data.roles;
  const groups = data.permission_groups;
  let selectedId = roles.length ? roles[0].id : null;

  host.innerHTML = `
    <div class="grid-2" style="grid-template-columns:280px 1fr;align-items:start">
      <div class="panel">
        <h3>${esc(t("admin_roles"))}
          <span style="float:right"><button class="btn btn-primary btn-sm" id="r-add">${esc(t("add"))}</button></span>
        </h3>
        <div id="r-list">
          ${roles.map((r) => `
            <button class="nav-item r-item ${r.id === selectedId ? "active" : ""}" data-id="${r.id}" style="width:100%">
              ${esc(langOf(r))} <span class="badge badge-gray">${esc(t("key"))}: ${esc(r.key)}</span>
            </button>`).join("")}
        </div>
      </div>
      <div class="panel" id="r-detail"><div class="hint">${esc(t("loading"))}</div></div>
    </div>`;

  const drawDetail = async () => {
    const role = roles.find((r) => r.id === selectedId);
    const detail = qs("#r-detail");
    if (!role) { detail.innerHTML = `<div class="hint">${esc(t("nothing"))}</div>`; return; }
    const mine = new Set(role.permissions || []);
    detail.innerHTML = `
      <h3>${esc(t("admin_roles"))} · ${esc(langOf(role))}
        ${role.is_system ? `<span class="badge badge-gray">${esc(t("key"))}: ${esc(role.key)}</span>` : ""}
      </h3>
      <div class="form-row">
        <div class="field"><label>${esc(t("name"))} (RU)</label>
          <input class="input" id="rm-ru" value="${esc(role.name_ru || "")}"></div>
        <div class="field"><label>${esc(t("name"))} (EN)</label>
          <input class="input" id="rm-en" value="${esc(role.name_en || "")}"></div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn btn-primary btn-sm" id="rm-save">${esc(t("save"))}</button>
        ${role.is_system ? "" : `<button class="btn btn-sm btn-danger" id="rm-del">${esc(t("delete"))}</button>`}
      </div>
      <h3>${esc(t("permissions"))}</h3>
      ${groups.map((g) => `
        <div style="margin-bottom:12px">
          <div class="nav-label" style="padding-left:0">${esc(getLang() === "en" ? g.en : g.ru)}</div>
          <div class="grid-3">
            ${g.items.map((p) => `
              <label class="checkbox perm-cb">
                <input type="checkbox" value="${esc(p.key)}" ${mine.has(p.key) ? "checked" : ""}>
                <span>${esc(langOf(p))}</span>
              </label>`).join("")}
          </div>
        </div>`).join("")}
      <button class="btn btn-primary" id="rp-save">${esc(t("save_permissions"))}</button>`;

    qs("#rm-save").onclick = async () => {
      try {
        await api.put(`/api/admin/roles/${role.id}`, {
          name_ru: qs("#rm-ru").value, name_en: qs("#rm-en").value,
        });
        toast(t("saved"), "success");
        await rerender();
      } catch (e) { toast(e.message, "error"); }
    };
    const del = qs("#rm-del");
    if (del) del.onclick = async () => {
      if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
      try {
        await api.del(`/api/admin/roles/${role.id}`);
        toast(t("saved"), "success");
        await rerender();
      } catch (e) { toast(e.message, "error"); }
    };
    qs("#rp-save").onclick = async () => {
      const perms = qsa(".perm-cb input", detail).filter((c) => c.checked).map((c) => c.value);
      try {
        await api.put(`/api/admin/roles/${role.id}/permissions`, { permissions: perms });
        toast(t("saved"), "success");
        role.permissions = perms;
      } catch (e) { toast(e.message, "error"); }
    };
  };

  qsa(".r-item", host).forEach((b) => (b.onclick = () => {
    selectedId = parseInt(b.dataset.id, 10);
    qsa(".r-item", host).forEach((x) => x.classList.toggle("active", x === b));
    drawDetail();
  }));

  qs("#r-add").onclick = () => {
    const wrap = openModal({
      title: t("add"),
      size: "sm",
      body: `<div class="field"><label>${esc(t("key"))} <span class="req">*</span></label>
               <input class="input" id="rn-key"></div>
             <div class="field"><label>${esc(t("name"))} (RU)</label><input class="input" id="rn-ru"></div>
             <div class="field"><label>${esc(t("name"))} (EN)</label><input class="input" id="rn-en"></div>
             <div class="error-text" id="rn-err"></div>`,
      footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
               <button class="btn btn-primary" id="rn-go">${esc(t("create"))}</button>`,
    });
    qs("#rn-go", wrap).onclick = async () => {
      try {
        await api.post("/api/admin/roles", {
          key: qs("#rn-key", wrap).value.trim(),
          name_ru: qs("#rn-ru", wrap).value.trim(),
          name_en: qs("#rn-en", wrap).value.trim(),
        });
        closeModal();
        toast(t("saved"), "success");
        await rerender();
      } catch (e) { qs("#rn-err", wrap).textContent = e.message || t("error"); }
    };
  };

  await drawDetail();
}

/* ============================================================= statuses */
async function tabStatuses(host) {
  const data = await api.get("/api/admin/statuses");
  const statuses = data.statuses;

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_statuses"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="s-add">${esc(t("add"))}</button></span>
      </h3>
      <div class="hint" style="margin-bottom:10px">${esc(t("delete_status_note"))}</div>
      <table class="tbl">
        <thead><tr>
          <th style="width:40px">${esc(t("position"))}</th><th>${esc(t("name"))}</th><th>${esc(t("key"))}</th>
          <th>${esc(t("color"))}</th><th>${esc(t("orders_on_status"))}</th><th>${esc(t("active"))}</th><th></th>
        </tr></thead>
        <tbody id="s-body">
          ${statuses.map((s, i) => `
            <tr data-id="${s.id}">
              <td style="white-space:nowrap">
                <button class="icon-btn s-up" data-i="${i}" style="width:24px;height:24px" ${i === 0 ? "disabled" : ""}>↑</button>
                <button class="icon-btn s-down" data-i="${i}" style="width:24px;height:24px" ${i === statuses.length - 1 ? "disabled" : ""}>↓</button>
              </td>
              <td><span class="column-dot" style="background:${esc(s.color)};display:inline-block;margin-right:6px"></span>
                <b>${esc(s.name_ru)}</b> / ${esc(s.name_en)}</td>
              <td><code>${esc(s.key)}</code></td>
              <td><input type="color" value="${esc(s.color)}" class="s-color" data-id="${s.id}" style="width:36px;height:26px;border:1px solid var(--border);border-radius:6px;padding:1px"></td>
              <td>${s.orders_count}</td>
              <td>${s.active ? `<span class="badge badge-green">${esc(t("active"))}</span>` : `<span class="badge badge-gray">—</span>`}</td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn btn-sm s-edit" data-id="${s.id}">${esc(t("edit"))}</button>
                ${s.is_system ? "" : `<button class="btn btn-sm btn-danger s-del" data-id="${s.id}">${esc(t("delete"))}</button>`}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  const move = async (i, dir) => {
    const order = statuses.map((s) => s.id);
    const j = i + dir;
    [order[i], order[j]] = [order[j], order[i]];
    try {
      await api.post("/api/admin/statuses/reorder", { order });
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };
  qsa(".s-up", host).forEach((b) => (b.onclick = () => move(parseInt(b.dataset.i, 10), -1)));
  qsa(".s-down", host).forEach((b) => (b.onclick = () => move(parseInt(b.dataset.i, 10), 1)));

  qsa(".s-color", host).forEach((inp) => (inp.onchange = async () => {
    const s = statuses.find((x) => x.id === parseInt(inp.dataset.id, 10));
    try {
      await api.put(`/api/admin/statuses/${s.id}`, { color: inp.value });
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  }));

  qsa(".s-edit", host).forEach((b) => (b.onclick = () => {
    const s = statuses.find((x) => x.id === parseInt(b.dataset.id, 10));
    statusModal(s, rerender);
  }));
  qsa(".s-del", host).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    try {
      await api.del(`/api/admin/statuses/${b.dataset.id}`);
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  }));
  qs("#s-add").onclick = () => statusModal(null, rerender);
}

function statusModal(status, onDone) {
  const isNew = !status;
  const wrap = openModal({
    title: isNew ? t("add") : status.name_ru,
    size: "sm",
    body: `
      <div class="form-row">
        <div class="field"><label>${esc(t("name"))} (RU) <span class="req">*</span></label>
          <input class="input" id="sm-ru" value="${esc(status ? status.name_ru : "")}"></div>
        <div class="field"><label>${esc(t("name"))} (EN)</label>
          <input class="input" id="sm-en" value="${esc(status ? status.name_en : "")}"></div>
      </div>
      ${isNew ? `<div class="field"><label>${esc(t("key"))}</label><input class="input" id="sm-key" value=""></div>` : ""}
      <div class="form-row">
        <div class="field"><label>${esc(t("color"))}</label>
          <input type="color" id="sm-color" value="${esc(status ? status.color : "#64748b")}" style="height:36px"></div>
        <div class="field"><label>${esc(t("position"))}</label>
          <input class="input" type="number" id="sm-pos" value="${status ? status.position : ""}"></div>
      </div>
      <label class="checkbox"><input type="checkbox" id="sm-active" ${!status || status.active ? "checked" : ""}> ${esc(t("active"))}</label>
      <div class="error-text" id="sm-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="sm-save">${esc(t("save"))}</button>`,
  });
  qs("#sm-save", wrap).onclick = async () => {
    const payload = {
      name_ru: qs("#sm-ru", wrap).value.trim(),
      name_en: qs("#sm-en", wrap).value.trim(),
      color: qs("#sm-color", wrap).value,
      position: qs("#sm-pos", wrap).value ? parseInt(qs("#sm-pos", wrap).value, 10) : undefined,
      active: qs("#sm-active", wrap).checked ? 1 : 0,
    };
    if (isNew) payload.key = qs("#sm-key", wrap).value.trim();
    try {
      if (isNew) await api.post("/api/admin/statuses", payload);
      else await api.put(`/api/admin/statuses/${status.id}`, payload);
      closeModal();
      toast(t("saved"), "success");
      onDone();
    } catch (e) { qs("#sm-err", wrap).textContent = e.message || t("error"); }
  };
}

/* =========================================================== work types */
async function tabWorktypes(host) {
  const data = await api.get("/api/admin/worktypes");
  const items = data.work_types;

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_worktypes"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="w-add">${esc(t("add"))}</button></span>
      </h3>
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("work_type_name"))}</th><th>${esc(t("orders_count"))}</th>
          <th>${esc(t("admin_checklists"))}</th><th>${esc(t("active"))}</th><th></th>
        </tr></thead>
        <tbody>
          ${items.map((w) => `
            <tr>
              <td><b>${esc(w.name_ru)}</b> / ${esc(w.name_en)}</td>
              <td>${w.orders_count}</td>
              <td>${(w.templates || []).length}</td>
              <td>${w.active ? `<span class="badge badge-green">${esc(t("active"))}</span>` : `<span class="badge badge-gray">—</span>`}</td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn btn-sm w-edit" data-id="${w.id}">${esc(t("edit"))}</button>
                <button class="btn btn-sm btn-danger w-del" data-id="${w.id}">${esc(t("delete"))}</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  qs("#w-add").onclick = () => wtModal(null, rerender);
  qsa(".w-edit", host).forEach((b) => (b.onclick = () => {
    wtModal(items.find((x) => x.id === parseInt(b.dataset.id, 10)), rerender);
  }));
  qsa(".w-del", host).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    try {
      await api.del(`/api/admin/worktypes/${b.dataset.id}`);
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  }));
}

function wtModal(wt, onDone) {
  const isNew = !wt;
  const wrap = openModal({
    title: isNew ? t("add") : wt.name_ru,
    size: "sm",
    body: `
      <div class="field"><label>${esc(t("name"))} (RU) <span class="req">*</span></label>
        <input class="input" id="wtm-ru" value="${esc(wt ? wt.name_ru : "")}"></div>
      <div class="field"><label>${esc(t("name"))} (EN)</label>
        <input class="input" id="wtm-en" value="${esc(wt ? wt.name_en : "")}"></div>
      <label class="checkbox"><input type="checkbox" id="wtm-active" ${!wt || wt.active ? "checked" : ""}> ${esc(t("active"))}</label>
      <div class="error-text" id="wtm-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="wtm-save">${esc(t("save"))}</button>`,
  });
  qs("#wtm-save", wrap).onclick = async () => {
    const payload = {
      name_ru: qs("#wtm-ru", wrap).value.trim(),
      name_en: qs("#wtm-en", wrap).value.trim(),
      active: qs("#wtm-active", wrap).checked ? 1 : 0,
    };
    try {
      if (isNew) await api.post("/api/admin/worktypes", payload);
      else await api.put(`/api/admin/worktypes/${wt.id}`, payload);
      closeModal();
      toast(t("saved"), "success");
      onDone();
    } catch (e) { qs("#wtm-err", wrap).textContent = e.message || t("error"); }
  };
}

/* ==================================================== checklist templates */
async function tabChecklists(host) {
  const data = await api.get("/api/admin/checklist-templates");
  const templates = data.templates;
  const workTypes = data.work_types;

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_checklists"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="c-add">${esc(t("add_template"))}</button></span>
      </h3>
      <div class="hint" style="margin-bottom:12px">${esc(t("duplicate_exists"))}</div>
      ${workTypes.map((w) => {
        const rows = templates.filter((x) => x.work_type_id === w.id);
        return `
          <div style="margin-bottom:16px">
            <div class="nav-label" style="padding-left:0">${esc(langOf(w))} <span class="badge badge-blue">${rows.length}</span></div>
            ${rows.length ? `
              <table class="tbl">
                <tbody>
                  ${rows.map((x) => `
                    <tr>
                      <td>${esc(x.text_ru)}${x.text_en && x.text_en !== x.text_ru ? ` / ${esc(x.text_en)}` : ""}</td>
                      <td style="width:120px">${x.stage_key ? `<span class="badge badge-gray">${esc(stageName(x.stage_key))}</span>` : "—"}</td>
                      <td style="width:90px">${x.required ? `<span class="badge badge-amber">★ ${esc(t("required"))}</span>` : "—"}</td>
                      <td style="width:130px;text-align:right;white-space:nowrap">
                        <button class="btn btn-sm c-edit" data-id="${x.id}">${esc(t("edit"))}</button>
                        <button class="btn btn-sm btn-danger c-del" data-id="${x.id}">${esc(t("delete"))}</button>
                      </td>
                    </tr>`).join("")}
                </tbody>
              </table>` : `<div class="hint">${esc(t("nothing"))}</div>`}
          </div>`;
      }).join("")}
    </div>`;

  qs("#c-add").onclick = () => cltModal(null, workTypes, rerender);
  qsa(".c-edit", host).forEach((b) => (b.onclick = () => {
    cltModal(templates.find((x) => x.id === parseInt(b.dataset.id, 10)), workTypes, rerender);
  }));
  qsa(".c-del", host).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    await api.del(`/api/admin/checklist-templates/${b.dataset.id}`);
    toast(t("saved"), "success");
    await rerender();
  }));
}

function stageName(key) {
  const st = state.meta.statuses.find((s) => s.key === key);
  return st ? langOf(st) : key;
}

function cltModal(tpl, workTypes, onDone) {
  const isNew = !tpl;
  const wrap = openModal({
    title: isNew ? t("add_template") : t("edit"),
    body: `
      <div class="field"><label>${esc(t("f_work_type"))} <span class="req">*</span></label>
        <select class="select" id="clt-wt">
          ${workTypes.map((w) => `<option value="${w.id}" ${tpl && tpl.work_type_id === w.id ? "selected" : ""}>${esc(langOf(w))}</option>`).join("")}
        </select></div>
      <div class="field"><label>${esc(t("checklist_text"))} (RU) <span class="req">*</span></label>
        <input class="input" id="clt-ru" value="${esc(tpl ? tpl.text_ru : "")}"></div>
      <div class="field"><label>${esc(t("checklist_text"))} (EN)</label>
        <input class="input" id="clt-en" value="${esc(tpl ? tpl.text_en || "" : "")}"></div>
      <div class="form-row">
        <div class="field"><label>${esc(t("stage"))}</label>
          <select class="select" id="clt-stage">
            <option value="">—</option>
            ${state.meta.statuses.map((s) => `<option value="${s.key}" ${tpl && tpl.stage_key === s.key ? "selected" : ""}>${esc(langOf(s))}</option>`).join("")}
          </select></div>
        <div class="field"><label>&nbsp;</label>
          <label class="checkbox"><input type="checkbox" id="clt-req" ${!tpl || tpl.required ? "checked" : ""}> ${esc(t("required"))}</label></div>
      </div>
      <div class="error-text" id="clt-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="clt-save">${esc(t("save"))}</button>`,
  });
  qs("#clt-save", wrap).onclick = async () => {
    const payload = {
      work_type_id: parseInt(qs("#clt-wt", wrap).value, 10),
      text_ru: qs("#clt-ru", wrap).value.trim(),
      text_en: qs("#clt-en", wrap).value.trim(),
      stage_key: qs("#clt-stage", wrap).value,
      required: qs("#clt-req", wrap).checked,
    };
    if (!payload.text_ru) { qs("#clt-err", wrap).textContent = t("checklist_text"); return; }
    try {
      if (isNew) await api.post("/api/admin/checklist-templates", payload);
      else await api.put(`/api/admin/checklist-templates/${tpl.id}`, payload);
      closeModal();
      toast(t("saved"), "success");
      onDone();
    } catch (e) { qs("#clt-err", wrap).textContent = e.message || t("error"); }
  };
}

/* ======================================================= card templates */
async function tabTemplates(host) {
  const data = await api.get("/api/admin/card-templates");
  const items = data.templates.map((x) => ({
    ...x,
    original_works: safeJson(x.original_works, []),
    work_type_ids: safeJson(x.work_type_ids, []),
  }));

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_templates"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="ct-add">${esc(t("add"))}</button></span>
      </h3>
      ${items.length ? `
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("template_name"))}</th><th>${esc(t("make"))}</th><th>${esc(t("model"))}</th>
          <th>${esc(t("f_priority"))}</th><th>${esc(t("work_types"))}</th><th>${esc(t("active"))}</th><th></th>
        </tr></thead>
        <tbody>
          ${items.map((x) => `
            <tr>
              <td><b>${esc(x.name)}</b></td>
              <td>${esc(x.make || "—")}</td>
              <td>${esc(x.model || "—")}</td>
              <td>${esc(t("prio_" + (x.priority || "normal")))}</td>
              <td>${x.work_type_ids.map((id) => {
                const w = state.meta.work_types.find((y) => y.id === id);
                return w ? `<span class="badge badge-blue">${esc(langOf(w))}</span>` : "";
              }).join(" ") || "—"}</td>
              <td>${x.active ? `<span class="badge badge-green">${esc(t("active"))}</span>` : `<span class="badge badge-gray">—</span>`}</td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn btn-sm ct-edit" data-id="${x.id}">${esc(t("edit"))}</button>
                <button class="btn btn-sm btn-danger ct-del" data-id="${x.id}">${esc(t("delete"))}</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<div class="hint">${esc(t("nothing"))}</div>`}
    </div>`;

  qs("#ct-add").onclick = () => ctModal(null, rerender);
  qsa(".ct-edit", host).forEach((b) => (b.onclick = () => {
    ctModal(items.find((x) => x.id === parseInt(b.dataset.id, 10)), rerender);
  }));
  qsa(".ct-del", host).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    await api.del(`/api/admin/card-templates/${b.dataset.id}`);
    toast(t("saved"), "success");
    await rerender();
  }));
}

function safeJson(value, fallback) {
  if (Array.isArray(value)) return value;
  try { return JSON.parse(value || "null") || fallback; } catch (e) { return fallback; }
}

function ctModal(tpl, onDone) {
  const isNew = !tpl;
  const wrap = openModal({
    title: isNew ? t("add") : (tpl ? tpl.name : ""),
    body: `
      <div class="field"><label>${esc(t("template_name"))} <span class="req">*</span></label>
        <input class="input" id="ctm-name" value="${esc(tpl ? tpl.name : "")}"></div>
      <div class="form-row-3">
        <div class="field"><label>${esc(t("make"))}</label><input class="input" id="ctm-make" value="${esc(tpl ? tpl.make || "" : "")}"></div>
        <div class="field"><label>${esc(t("model"))}</label><input class="input" id="ctm-model" value="${esc(tpl ? tpl.model || "" : "")}"></div>
        <div class="field"><label>${esc(t("year"))}</label><input class="input" type="number" id="ctm-year" value="${esc(tpl && tpl.year ? tpl.year : "")}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("f_priority"))}</label>
          <select class="select" id="ctm-prio">
            <option value="normal" ${tpl && tpl.priority === "normal" ? "selected" : ""}>${esc(t("prio_normal"))}</option>
            <option value="urgent" ${tpl && tpl.priority === "urgent" ? "selected" : ""}>${esc(t("prio_urgent"))}</option>
            <option value="critical" ${tpl && tpl.priority === "critical" ? "selected" : ""}>${esc(t("prio_critical"))}</option>
          </select></div>
        <div class="field"><label>${esc(t("active"))}</label>
          <label class="checkbox"><input type="checkbox" id="ctm-active" ${!tpl || tpl.active ? "checked" : ""}> ${esc(t("active"))}</label></div>
      </div>
      <div class="field"><label>${esc(t("problem"))}</label>
        <textarea class="textarea" id="ctm-problem">${esc(tpl ? tpl.problem || "" : "")}</textarea></div>
      <div class="field"><label>${esc(t("notes"))}</label>
        <textarea class="textarea" id="ctm-works">${esc((tpl ? tpl.original_works : []).join("\n"))}</textarea>
        <div class="hint">${esc(t("notes_line"))}</div></div>
      <div class="field"><label>${esc(t("work_types"))}</label>
        <select class="select" id="ctm-wt" multiple size="4" style="height:auto">
          ${state.meta.work_types.map((w) => `<option value="${w.id}" ${tpl && tpl.work_type_ids.includes(w.id) ? "selected" : ""}>${esc(langOf(w))}</option>`).join("")}
        </select></div>
      <div class="error-text" id="ctm-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="ctm-save">${esc(t("save"))}</button>`,
  });
  qs("#ctm-save", wrap).onclick = async () => {
    const payload = {
      name: qs("#ctm-name", wrap).value.trim(),
      make: qs("#ctm-make", wrap).value.trim(),
      model: qs("#ctm-model", wrap).value.trim(),
      year: qs("#ctm-year", wrap).value ? parseInt(qs("#ctm-year", wrap).value, 10) : null,
      priority: qs("#ctm-prio", wrap).value,
      active: qs("#ctm-active", wrap).checked ? 1 : 0,
      problem: qs("#ctm-problem", wrap).value,
      original_works: qs("#ctm-works", wrap).value.split("\n").map((s) => s.trim()).filter(Boolean),
      work_type_ids: qsa("#ctm-wt option", wrap).filter((o) => o.selected).map((o) => parseInt(o.value, 10)),
    };
    if (!payload.name) { qs("#ctm-err", wrap).textContent = t("name"); return; }
    try {
      if (isNew) await api.post("/api/admin/card-templates", payload);
      else await api.put(`/api/admin/card-templates/${tpl.id}`, payload);
      closeModal();
      toast(t("saved"), "success");
      onDone();
    } catch (e) { qs("#ctm-err", wrap).textContent = e.message || t("error"); }
  };
}

/* ============================================================== settings */
async function tabSettings(host) {
  const data = await api.get("/api/admin/settings");
  const s = data.settings;
  const reasons = (s.cancel_reasons || []).slice();
  const cond = s.ready_conditions || { vin: true, checklist: true, responsible: true };
  const matrix = s.notify_matrix || {};

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("general_settings"))}</h3>
      <div class="form-row">
        <div class="field"><label>${esc(t("service_name"))}</label>
          <input class="input" id="se-service" value="${esc(s.service_name || "")}"></div>
        <div class="field"><label>${esc(t("default_lang"))}</label>
          <select class="select" id="se-lang">
            <option value="ru" ${s.default_lang === "ru" ? "selected" : ""}>RU</option>
            <option value="en" ${s.default_lang === "en" ? "selected" : ""}>EN</option>
          </select></div>
      </div>
      <div class="form-row-3">
        <div class="field"><label>${esc(t("tz_offset"))}</label>
          <input class="input" type="number" id="se-tz" value="${esc(s.org_tz_offset)}"></div>
        <div class="field"><label>${esc(t("session_timeout"))}</label>
          <input class="input" type="number" id="se-session" value="${esc(s.session_timeout_min)}"></div>
        <div class="field"><label>${esc(t("due_soon"))}</label>
          <input class="input" type="number" id="se-duesoon" value="${esc(s.due_soon_hours)}"></div>
      </div>
      <div class="form-row-3">
        <div class="field"><label>${esc(t("overdue_repeat"))}</label>
          <input class="input" type="number" id="se-repeat" value="${esc(s.overdue_repeat_hours)}"></div>
        <div class="field"><label>${esc(t("backup_keep"))}</label>
          <input class="input" type="number" id="se-keep" value="${esc(s.backup_keep_days)}"></div>
        <div class="field"><label>${esc(t("backup_time"))}</label>
          <input class="input" type="time" id="se-btime" value="${esc(s.backup_time || "03:00")}"></div>
      </div>
      <div class="switch">
        <div><b>${esc(t("auto_assign_enabled"))}</b><div class="hint">${esc(t("auto_assign_rule"))}</div></div>
        <input type="checkbox" id="se-autoassign" ${s.auto_assign && s.auto_assign.enabled ? "checked" : ""}>
      </div>

      <h3 style="margin-top:20px">${esc(t("ready_conditions"))}</h3>
      <label class="checkbox" style="margin-bottom:6px"><input type="checkbox" id="se-cond-vin" ${cond.vin ? "checked" : ""}> ${esc(t("cond_vin"))}</label>
      <label class="checkbox" style="margin-bottom:6px"><input type="checkbox" id="se-cond-checklist" ${cond.checklist ? "checked" : ""}> ${esc(t("cond_checklist"))}</label>
      <label class="checkbox"><input type="checkbox" id="se-cond-resp" ${cond.responsible ? "checked" : ""}> ${esc(t("cond_responsible"))}</label>

      <div style="margin-top:18px">
        <button class="btn btn-primary" id="se-save">${esc(t("save"))}</button>
      </div>
    </div>

    <div class="panel" style="margin-top:14px">
      <h3>${esc(t("cancel_reasons"))}
        <span style="float:right"><button class="btn btn-sm" id="cr-add">${esc(t("cancel_reason_add"))}</button></span>
      </h3>
      <div id="cr-list">
        ${reasons.map((r, i) => `
          <div class="form-row cr-row" data-i="${i}">
            <div class="field" style="margin:0"><label>${esc(t("key"))}</label>
              <input class="input cr-key" value="${esc(r.key)}"></div>
            <div class="field" style="margin:0"><label>RU</label><input class="input cr-ru" value="${esc(r.ru || "")}"></div>
            <div class="field" style="margin:0"><label>EN</label><input class="input cr-en" value="${esc(r.en || "")}"></div>
            <div class="field" style="margin:0"><label>&nbsp;</label>
              <button class="btn btn-sm btn-danger cr-del" data-i="${i}">${esc(t("delete"))}</button></div>
          </div>`).join("")}
      </div>
      <button class="btn btn-primary btn-sm" id="cr-save" style="margin-top:8px">${esc(t("save"))}</button>
    </div>

    <div class="panel" style="margin-top:14px">
      <h3>${esc(t("notify_matrix"))}</h3>
      <div class="hint" style="margin-bottom:10px">${esc(t("notify_type"))} × ${esc(t("role_col"))}</div>
      <div style="overflow-x:auto">
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("notify_type"))}</th>
          ${s.roles.map((r) => `<th style="text-align:center">${esc(langOf(r))}</th>`).join("")}
        </tr></thead>
        <tbody>
          ${[...(s.notify_types || []), ...(s.client_types || [])].map((ty) => `
            <tr>
              <td>${esc(getLang() === "en" ? ty.en : ty.ru)}</td>
              ${s.roles.map((r) => {
                const on = !(matrix[ty.key] && matrix[ty.key][r.key] === false);
                return `<td style="text-align:center">
                  <input type="checkbox" class="nm-cb" data-type="${esc(ty.key)}" data-role="${esc(r.key)}" ${on ? "checked" : ""}>
                </td>`;
              }).join("")}
            </tr>`).join("")}
        </tbody>
      </table>
      </div>
      <button class="btn btn-primary btn-sm" id="nm-save" style="margin-top:10px">${esc(t("save"))}</button>
    </div>`;

  qs("#se-save").onclick = async () => {
    try {
      await api.put("/api/admin/settings", {
        service_name: qs("#se-service").value.trim(),
        default_lang: qs("#se-lang").value,
        org_tz_offset: parseInt(qs("#se-tz").value, 10) || 0,
        session_timeout_min: parseInt(qs("#se-session").value, 10) || 60,
        due_soon_hours: parseInt(qs("#se-duesoon").value, 10) || 24,
        overdue_repeat_hours: parseInt(qs("#se-repeat").value, 10) || 6,
        backup_keep_days: parseInt(qs("#se-keep").value, 10) || 30,
        backup_time: qs("#se-btime").value || "03:00",
        auto_assign: { enabled: qs("#se-autoassign").checked, rule: "least_loaded" },
        ready_conditions: {
          vin: qs("#se-cond-vin").checked,
          checklist: qs("#se-cond-checklist").checked,
          responsible: qs("#se-cond-resp").checked,
        },
      });
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };

  const collectReasons = () =>
    qsa("#cr-list .form-row").map((row) => ({
      key: qs(".cr-key", row).value.trim(),
      ru: qs(".cr-ru", row).value.trim(),
      en: qs(".cr-en", row).value.trim(),
    })).filter((r) => r.key);

  const bindReasonDel = (btn) => {
    btn.onclick = async () => {
      if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
      btn.closest(".form-row").remove();
    };
  };
  qsa(".cr-del", host).forEach(bindReasonDel);

  qs("#cr-add").onclick = () => {
    const list = qs("#cr-list");
    const i = list.children.length;
    const div = document.createElement("div");
    div.className = "form-row cr-row";
    div.dataset.i = i;
    div.innerHTML = `
      <div class="field" style="margin:0"><label>${esc(t("key"))}</label><input class="input cr-key" value=""></div>
      <div class="field" style="margin:0"><label>RU</label><input class="input cr-ru" value=""></div>
      <div class="field" style="margin:0"><label>EN</label><input class="input cr-en" value=""></div>
      <div class="field" style="margin:0"><label>&nbsp;</label><button class="btn btn-sm btn-danger cr-del">${esc(t("delete"))}</button></div>`;
    list.appendChild(div);
    bindReasonDel(qs(".cr-del", div));
  };
  qs("#cr-save").onclick = async () => {
    try {
      await api.put("/api/admin/settings", { cancel_reasons: collectReasons() });
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };

  qs("#nm-save").onclick = async () => {
    const m = {};
    qsa(".nm-cb", host).forEach((cb) => {
      if (!cb.checked) {
        m[cb.dataset.type] = m[cb.dataset.type] || {};
        m[cb.dataset.type][cb.dataset.role] = false;
      }
    });
    try {
      await api.put("/api/admin/settings", { notify_matrix: m });
      toast(t("saved"), "success");
    } catch (e) { toast(e.message, "error"); }
  };
}

/* ============================================================== telegram */
async function tabTelegram(host) {
  const data = await api.get("/api/admin/telegram");
  const bot = data.bot;
  const st = data.settings;

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("telegram_settings"))}</h3>
      <dl class="kv">
        <dt>${esc(t("telegram_bot"))}</dt>
        <dd>${bot && bot.ok
          ? `<b>${esc(bot.username || bot.login || "")}</b> <span class="badge badge-green">✓</span>`
          : `<span class="badge badge-red">${esc(t("tg_no_bot"))}</span>`}</dd>
        <dt>${esc(t("telegram_token"))}</dt>
        <dd>${st.token_set ? `<span class="badge badge-green">✓</span>` : `<span class="badge badge-amber">—</span>`}</dd>
        <dt>${esc(t("telegram_bot"))} (login)</dt>
        <dd>${esc(st.telegram_bot_login || "—")}</dd>
      </dl>
      ${can("settings.manage") ? `
        <div class="form-row">
          <div class="field"><label>${esc(t("telegram_token"))}</label>
            <input class="input" id="tg-token" type="password" placeholder="${st.token_set ? "••••••••" : ""}"></div>
          <div class="field"><label>${esc(t("telegram_bot"))}</label>
            <input class="input" id="tg-login" value="${esc(st.telegram_bot_login || "")}"></div>
        </div>
        <button class="btn btn-primary" id="tg-save">${esc(t("save"))}</button>
        <span class="hint" style="margin-left:10px">${esc(t("telegram_check"))}</span>
      ` : ""}
      <div class="error-text" id="tg-err" style="margin-top:8px"></div>
    </div>`;

  const save = qs("#tg-save");
  if (save) save.onclick = async () => {
    const payload = { telegram_bot_login: qs("#tg-login").value.trim() };
    const token = qs("#tg-token").value;
    if (token) payload.telegram_token = token;
    try {
      await api.put("/api/admin/settings", payload);
      toast(t("saved"), "success");
      await rerender();
    } catch (e) { qs("#tg-err").textContent = e.message || t("error"); }
  };
}

/* ================================================================ backup */
async function tabBackup(host) {
  const data = await api.get("/api/admin/backups");
  const backups = data.backups || [];
  const st = data.settings || {};

  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_backup"))}
        <span style="float:right"><button class="btn btn-primary btn-sm" id="bk-now">${esc(t("backup_now"))}</button></span>
      </h3>
      <div class="hint" style="margin-bottom:10px">
        ${esc(t("backup_keep"))}: ${esc(st.backup_keep_days)} · ${esc(t("backup_time"))}: ${esc(st.backup_time)}
      </div>
      ${backups.length ? `
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("name"))}</th><th>${esc(t("audit_time"))}</th><th>${esc(t("size"))}</th><th></th>
        </tr></thead>
        <tbody>
          ${backups.map((b) => `
            <tr>
              <td><code>${esc(b.filename)}</code></td>
              <td>${esc(fmtDateTime(b.created_at))}</td>
              <td>${(b.size / 1024 / 1024).toFixed(2)} MB</td>
              <td style="text-align:right">
                <button class="btn btn-sm btn-danger bk-restore" data-id="${b.id}">${esc(t("restore"))}</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<div class="hint">${esc(t("nothing"))}</div>`}
    </div>`;

  qs("#bk-now").onclick = async () => {
    try {
      await api.post("/api/admin/backups");
      toast(t("backup_created"), "success");
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };
  qsa(".bk-restore", host).forEach((b) => (b.onclick = async () => {
    const wrap = openModal({
      title: t("restore_confirm_title"),
      body: `<div class="alert alert-warn">${esc(t("restore_confirm_text"))}</div>`,
      footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
               <button class="btn btn-danger" id="bk-go">${esc(t("restore_confirm_btn"))}</button>`,
    });
    qs("#bk-go", wrap).onclick = async () => {
      try {
        await api.post(`/api/admin/backups/${b.dataset.id}/restore`, { confirm: true });
        closeModal();
        toast(t("restored"), "success");
        setTimeout(() => location.reload(), 800);
      } catch (e) { toast(e.message, "error"); }
    };
  }));
}

/* ================================================================= audit */
async function tabAudit(host) {
  const flt = { user_id: "", action: "" };
  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("admin_audit"))}</h3>
      <div class="filters-panel" style="display:grid;margin-bottom:12px">
        <div class="field"><label>${esc(t("audit_user"))}</label>
          <select class="select" id="au-user"><option value="">${esc(t("f_any"))}</option></select></div>
        <div class="field"><label>${esc(t("audit_action"))}</label>
          <input class="input" id="au-action" placeholder="login, order…"></div>
        <div class="field"><label>&nbsp;</label><button class="btn" id="au-reset">${esc(t("reset_filters"))}</button></div>
      </div>
      <div id="au-list"><div class="hint">${esc(t("loading"))}</div></div>
    </div>`;

  const load = async () => {
    const data = await api.get("/api/admin/audit" + api.qs({ limit: 300, ...flt }));
    const sel = qs("#au-user");
    sel.innerHTML = `<option value="">${esc(t("f_any"))}</option>` +
      data.users.map((u) => `<option value="${u.id}" ${String(flt.user_id) === String(u.id) ? "selected" : ""}>${esc(u.full_name || u.login)}</option>`).join("");
    qs("#au-list").innerHTML = data.audit.length ? `
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("audit_time"))}</th><th>${esc(t("audit_user"))}</th>
          <th>${esc(t("audit_action"))}</th><th>${esc(t("audit_object"))}</th><th>${esc(t("old_value"))}</th>
        </tr></thead>
        <tbody>
          ${data.audit.map((a) => `
            <tr>
              <td style="white-space:nowrap">${esc(fmtDateTime(a.created_at))}</td>
              <td>${esc(a.full_name || a.login || "—")}</td>
              <td><code>${esc(a.action)}</code></td>
              <td>${esc([a.entity, a.entity_id].filter(Boolean).join(":"))}</td>
              <td class="hint">${esc((a.detail || "").slice(0, 90))}</td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<div class="hint">${esc(t("nothing"))}</div>`;
    qs("#au-user").onchange = (e) => { flt.user_id = e.target.value; load(); };
  };

  qs("#au-action").value = flt.action;
  qs("#au-action").addEventListener("input", debounce(() => { flt.action = qs("#au-action").value.trim(); load(); }, 400));
  qs("#au-reset").onclick = () => { flt.user_id = ""; flt.action = ""; qs("#au-action").value = ""; load(); };
  await load();
}

/* ================================================================= trash */
async function tabTrash(host) {
  let view = "deleted";

  const load = async () => {
    const data = await api.get("/api/admin/orders" + api.qs({ view }));
    const orders = data.orders || [];
    host.innerHTML = `
      <div class="panel">
        <h3>${esc(t("admin_trash"))}
          <span style="float:right">
            <button class="chip ${view === "deleted" ? "active" : ""}" id="tv-del">${esc(t("view_deleted"))}</button>
            <button class="chip ${view === "archived" ? "active" : ""}" id="tv-arch">${esc(t("view_archived"))}</button>
          </span>
        </h3>
        ${orders.length ? `
        <table class="tbl">
          <thead><tr>
            <th>${esc(t("order"))}</th><th>${esc(t("plate"))}</th><th>${esc(t("make"))}</th>
            <th>${esc(t("f_status"))}</th><th>${esc(t("client_name"))}</th>
            <th>${view === "deleted" ? esc(t("audit_time")) : esc(t("last_visit"))}</th><th></th>
          </tr></thead>
          <tbody>
            ${orders.map((o) => `
              <tr>
                <td><b>${esc(o.number)}</b></td>
                <td>${esc(o.plate || "—")}</td>
                <td>${esc([o.make, o.model].filter(Boolean).join(" "))}</td>
                <td>${esc(langOf({ name_ru: o.status_ru, name_en: o.status_en }))}</td>
                <td>${esc(o.client_name || "—")}</td>
                <td>${esc(fmtDateTime(view === "deleted" ? o.deleted_at : o.updated_at))}</td>
                <td style="text-align:right;white-space:nowrap">
                  <button class="btn btn-sm tr-open" data-id="${o.id}">${esc(t("open_order"))}</button>
                  ${view === "archived" && can("order.archive")
                    ? `<button class="btn btn-sm tr-unarch" data-id="${o.id}">${esc(t("unarchive"))}</button>` : ""}
                  ${view === "deleted" && can("order.restore")
                    ? `<button class="btn btn-primary btn-sm tr-restore" data-id="${o.id}">${esc(t("restore"))}</button>` : ""}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>` : `<div class="hint">${esc(t("nothing"))}</div>`}
      </div>`;

    qs("#tv-del").onclick = () => { view = "deleted"; load(); };
    qs("#tv-arch").onclick = () => { view = "archived"; load(); };
    qsa(".tr-open", host).forEach((b) => (b.onclick = () => navigate("#/order/" + b.dataset.id)));
    qsa(".tr-unarch", host).forEach((b) => (b.onclick = async () => {
      try {
        await api.post(`/api/orders/${b.dataset.id}/archive`, { archive: false });
        toast(t("saved"), "success");
        load();
      } catch (e) { toast(e.message, "error"); }
    }));
    qsa(".tr-restore", host).forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog(t("confirm_restore"), { okLabel: t("restore") }))) return;
      try {
        await api.post(`/api/orders/${b.dataset.id}/restore`);
        toast(t("saved"), "success");
        load();
      } catch (e) { toast(e.message, "error"); }
    }));
  };

  await load();
}
