import * as api from "../api.js";
import { t, nameOf as langOf, getLang } from "../i18n.js";
import {
  esc, qs, qsa, toast, openModal, closeModal, fmtDate, fmtDateTime, fmtDuration,
  isOverdue, confirmDialog, copyText,
} from "../ui.js";
import { state, can, navigate, icon } from "../app.js";

let order = null;
let tab = "main";

export async function renderOrder(container, [id]) {
  tab = sessionStorage.getItem("order_tab") || "main";
  await load(container, id);
}

async function load(container, id) {
  const data = await api.get("/api/orders/" + id);
  order = data.order;
  draw(container);
}

function draw(container) {
  const o = order;
  const st = o.status || {};
  const late = isOverdue(o);
  container.innerHTML = `
    <div class="page">
      <div class="order-head">
        <div>
          <div><span class="plate-big">${esc(o.plate || "—")}</span>
            <span class="prio prio-${o.priority}">${esc(t("prio_" + o.priority))}</span></div>
          <div class="car">${esc([o.make, o.model].filter(Boolean).join(" "))} ${o.year ? "· " + esc(o.year) : ""}</div>
          <div class="num">${esc(t("order"))} ${esc(o.number)} · ${esc(fmtDate(o.created_at))}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <span class="status-chip"><span class="column-dot" style="background:${esc(st.color || "")}"></span>${esc(langOf(st))}</span>
          ${late ? `<span class="badge badge-red">⚠ ${esc(t("overdue"))}</span>` : ""}
          ${o.parts_attention ? `<span class="badge badge-amber">⚠ ${esc(t("attention"))}</span>` : ""}
          ${o.archive ? `<span class="badge badge-gray">${esc(t("archive_view"))}</span>` : ""}
          ${o.approval_state ? `<span class="badge badge-${o.approval_state === "full" ? "green" : o.approval_state === "rejected" ? "red" : "amber"}">${esc(approvalLabel(o.approval_state))}</span>` : ""}
        </div>
        <div style="flex:1"></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap" id="head-actions">
          ${can("order.move") ? moveSelect() : ""}
          ${hasActions() ? `<div class="dropdown"><button class="btn btn-sm" id="btn-actions">⋯</button></div>` : ""}
        </div>
      </div>

      <div id="ready-banner"></div>

      <div class="tabs" id="order-tabs">
        ${tabBtn("main", t("tab_main"))}
        ${tabBtn("works", t("tab_works"))}
        ${tabBtn("checklist", t("tab_checklist"))}
        ${tabBtn("time", t("tab_time"))}
        ${tabBtn("comments", t("tab_comments"))}
        ${tabBtn("history", t("tab_history"))}
        ${tabBtn("vin", t("tab_vin"))}
      </div>
      <div id="order-body"></div>
    </div>`;

  drawBanner();
  qsa("#order-tabs .tab").forEach((b) => (b.onclick = () => {
    tab = b.dataset.tab;
    sessionStorage.setItem("order_tab", tab);
    qsa("#order-tabs .tab").forEach((x) => x.classList.toggle("active", x === b));
    drawBody();
  }));
  qs(`#order-tabs .tab[data-tab="${tab}"]`)?.classList.add("active");
  const mv = qs("#move-select");
  if (mv) mv.onchange = () => doMove(parseInt(mv.value, 10));
  const btn = qs("#btn-actions");
  if (btn) btn.onclick = (e) => { e.stopPropagation(); actionsMenu(); };
  drawBody();
}

function tabBtn(key, label) {
  return `<button class="tab ${tab === key ? "active" : ""}" data-tab="${key}">${esc(label)}</button>`;
}

function approvalLabel(state_) {
  return t("approval_state_" + (state_ === "full" ? "full" : state_ === "rejected" ? "rejected" : "partial"));
}

function moveSelect() {
  const statuses = state.meta.statuses;
  return `<select class="select btn-sm" id="move-select" style="width:auto;padding:6px 10px">
    <option value="">${esc(t("move_to"))}…</option>
    ${statuses.map((s) => `<option value="${s.id}" ${s.id === order.status_id ? "disabled" : ""}>${esc(langOf(s))}</option>`).join("")}
  </select>`;
}

function drawBanner() {
  const host = qs("#ready-banner");
  if (!host) return;
  const problems = order.ready_problems || [];
  if (!problems.length || ["issued", "cancelled"].includes(order.status_key)) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = `<div class="alert alert-warn"><div>
      <b>${esc(t("ready_blocked"))}</b>
      <ul style="margin:6px 0 0 16px;padding:0">${problems.map((p) => `<li>${esc(t("p_" + p.code))}</li>`).join("")}</ul>
    </div></div>`;
}

function hasActions() {
  return can("order.edit") || can("order.duplicate") ||
    ((can("order.archive") || can("order.delete")) && !order.deleted) ||
    (can("order.restore") && order.deleted);
}

function actionsMenu() {
  const host = qs("#btn-actions").parentElement;
  const wasOpen = !!host.querySelector(".dropdown-menu");
  qsa(".dropdown-menu").forEach((m) => m.remove());
  if (wasOpen) return;
  const menu = document.createElement("div");
  menu.className = "dropdown-menu";
  const items = [];
  if (can("order.edit")) items.push(`<button id="a-edit">${esc(t("edit"))}</button>`);
  if (can("order.duplicate")) items.push(`<button id="a-dup">${esc(t("duplicate"))}</button>`);
  if (can("order.archive") && !order.deleted) items.push(`<button id="a-arch">${esc(order.archive ? t("unarchive") : t("archive"))}</button>`);
  if (can("order.delete") && !order.deleted) items.push(`<button class="danger" id="a-del">${esc(t("delete"))}</button>`);
  if (can("order.restore") && order.deleted) items.push(`<button id="a-rest">${esc(t("restore"))}</button>`);
  menu.innerHTML = items.join('<div class="sep"></div>');
  host.appendChild(menu);
  const bind = (id, fn) => { const el = qs(id, menu); if (el) el.onclick = fn; };
  bind("#a-edit", () => { menu.remove(); editModal(); });
  bind("#a-dup", async () => {
    menu.remove();
    const data = await api.post(`/api/orders/${order.id}/duplicate`);
    toast(data.order.number, "success");
    navigate("#/order/" + data.order.id);
  });
  bind("#a-arch", async () => {
    menu.remove();
    await api.post(`/api/orders/${order.id}/archive`, { archive: !order.archive });
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  });
  bind("#a-del", async () => {
    menu.remove();
    if (await confirmDialog(t("confirm_delete_order"), { danger: true, okLabel: t("delete") })) {
      await api.del(`/api/orders/${order.id}`);
      toast(t("saved"), "success");
      navigate("#/");
    }
  });
  bind("#a-rest", async () => {
    menu.remove();
    await api.post(`/api/orders/${order.id}/restore`);
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  });
}

async function doMove(statusId) {
  if (!statusId) return;
  try {
    await api.post(`/api/orders/${order.id}/move`, { status_id: statusId, version: order.version });
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  } catch (err) {
    if (err.code === "ready_conditions") {
      const problems = err.data.problems || [];
      const conflict = problems.find((p) => p.code === "vin_conflict");
      if (conflict) return vinConflictModal(statusId, conflict);
      if (problems.some((p) => p.code === "vin_required")) return promptVin(statusId);
      const wrap = openModal({
        title: t("ready_blocked"),
        body: `<ul style="margin:0;padding-left:18px">${problems.map((p) => `<li>${esc(t("p_" + p.code))}${p.items ? "<ul>" + p.items.map((i) => `<li>${esc(i)}</li>`).join("") + "</ul>" : ""}</li>`).join("")}</ul>`,
        footer: `<button class="btn btn-primary" data-close>${esc(t("close"))}</button>`,
      });
      return;
    }
    if (err.code === "cancel_reason_required") return cancelModal(statusId);
    toast(err.message || t("error"), "error");
  }
}

function cancelModal(statusId) {
  const reasons = (state.meta && state.meta.cancel_reasons) || [];
  const wrap = openModal({
    title: t("cancel_title"),
    size: "sm",
    body: `<div class="field"><label>${esc(t("cancel_reason"))} <span class="req">*</span></label>
      <select class="select" id="cm-reason"><option value="">${esc(t("select_value"))}</option>
      ${reasons.map((r) => `<option value="${esc(r.key)}">${esc(r.ru)}</option>`).join("")}</select>
      <div class="error-text" id="cm-err"></div></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-danger" id="cm-go">${esc(t("cancel_order"))}</button>`,
  });
  qs("#cm-go", wrap).onclick = async () => {
    const reason = qs("#cm-reason", wrap).value;
    if (!reason) { qs("#cm-err", wrap).textContent = t("cancel_required"); return; }
    closeModal();
    try {
      await api.post(`/api/orders/${order.id}/move`, { status_id: statusId, reason, version: order.version });
      toast(t("saved"), "success");
      await load(qs("#view"), order.id);
    } catch (e) { toast(e.message, "error"); }
  };
}

function vinConflictModal(statusId, conflict) {
  const wrap = openModal({
    title: t("p_vin_conflict"),
    body: `<div class="alert alert-warn"><b>${esc(t("history_of_vin"))}</b> VIN: ${esc(conflict.history?.[0]?.vin || order.vin)}</div>
      ${(conflict.history || []).map((h) => `
        <div class="candidate"><div class="cinfo">
          <div class="cplate">${esc(h.plate)} · ${esc(h.number)}</div>
          <div class="csub">${esc([h.make, h.model].filter(Boolean).join(" "))} · ${esc(h.client_name || "")}</div>
          <div class="cdate">${esc(fmtDate(h.created_at))} · ${esc(h.status_ru || "")}</div>
        </div></div>`).join("")}`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn" id="vc-edit">${esc(t("merge_edit_vin"))}</button>
             <button class="btn btn-primary" id="vc-merge">${esc(t("merge_confirm"))}</button>`,
  });
  qs("#vc-merge", wrap).onclick = async () => {
    closeModal();
    try {
      await api.post(`/api/orders/${order.id}/move`, {
        status_id: statusId, accept_vin_merge: true, version: order.version,
      });
      toast(t("merged_ok"), "success");
      await load(qs("#view"), order.id);
    } catch (e) { toast(e.message, "error"); }
  };
  qs("#vc-edit", wrap).onclick = () => { closeModal(); editModal(); };
}

function promptVin(statusId) {
  const wrap = openModal({
    title: t("vin"),
    size: "sm",
    body: `<div class="field"><label>${esc(t("vin"))} <span class="req">*</span></label>
      <input class="input" id="pv-vin" value="${esc(order.vin || "")}"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="pv-go">${esc(t("save"))}</button>`,
  });
  qs("#pv-go", wrap).onclick = async () => {
    const vin = qs("#pv-vin", wrap).value.trim();
    closeModal();
    try {
      await api.put(`/api/orders/${order.id}`, { vin });
      await api.post(`/api/orders/${order.id}/move`, { status_id: statusId, version: order.version + 1 });
      toast(t("saved"), "success");
      await load(qs("#view"), order.id);
    } catch (e) { toast(e.message, "error"); }
  };
}

/* ================================================================ tabs */
function drawBody() {
  const host = qs("#order-body");
  if (!host) return;
  const renderers = { main: tabMain, works: tabWorks, checklist: tabChecklist, time: tabTime, comments: tabComments, history: tabHistory, vin: tabVin };
  (renderers[tab] || tabMain)(host);
}

function tabMain(host) {
  const o = order;
  const users = o.users || {};
  host.innerHTML = `
    <div class="grid-2">
      <div class="panel">
        <h3>${esc(t("tab_main"))}
          ${can("order.edit") ? `<span style="float:right"><button class="btn btn-sm" id="btn-edit">${esc(t("edit"))}</button></span>` : ""}
        </h3>
        <dl class="kv">
          <dt>${esc(t("plate"))}</dt><dd><b>${esc(o.plate || "—")}</b></dd>
          <dt>${esc(t("vin"))}</dt><dd>${esc(o.vin || "—")}</dd>
          <dt>${esc(t("make"))} / ${esc(t("model"))}</dt><dd>${esc([o.make, o.model].filter(Boolean).join(" ") || "—")}</dd>
          <dt>${esc(t("year"))}</dt><dd>${esc(o.year || "—")}</dd>
          <dt>${esc(t("client_name"))}</dt><dd>${esc(o.client_name || "—")}</dd>
          <dt>${esc(t("client_phone"))}</dt><dd>${esc(o.client_phone || "—")}</dd>
          <dt>${esc(t("client_telegram"))}</dt><dd>${esc(o.client_telegram || "—")}</dd>
          <dt>${esc(t("problem"))}</dt><dd>${esc(o.problem || "—")}</dd>
          <dt>${esc(t("due_at"))}</dt><dd>${esc(fmtDateTime(o.due_at))}${isOverdue(o) ? ' <span class="badge badge-red">' + esc(t("overdue")) + "</span>" : ""}</dd>
          <dt>${esc(t("responsible"))}</dt>
          <dd>
            ${can("order.assign") ? `<select class="select" id="sel-resp" style="width:auto;max-width:260px;display:inline-block">
              <option value="">${esc(t("nobody"))}</option>
              ${Object.entries(users).map(([uid, name]) => `<option value="${uid}" ${String(o.responsible_id) === uid ? "selected" : ""}>${esc(name)}</option>`).join("")}
            </select>` : esc(o.responsible_name || t("nobody"))}
            ${o.responsible ? (o.responsible.telegram ? '<span class="badge badge-green">Telegram ✓</span>' : `<span class="badge badge-amber">${esc(t("tg_not_linked"))}</span>`) : ""}
          </dd>
          <dt>${esc(t("priority"))}</dt>
          <dd>${can("order.priority") ? `<select class="select" id="sel-prio" style="width:auto;display:inline-block">
              <option value="normal" ${o.priority === "normal" ? "selected" : ""}>${esc(t("prio_normal"))}</option>
              <option value="urgent" ${o.priority === "urgent" ? "selected" : ""}>${esc(t("prio_urgent"))}</option>
              <option value="critical" ${o.priority === "critical" ? "selected" : ""}>${esc(t("prio_critical"))}</option>
            </select>` : esc(t("prio_" + o.priority))}</dd>
          <dt>${esc(t("work_types"))}</dt>
          <dd>${(o.work_types || []).map((w) => `<span class="badge badge-blue">${esc(w.name)}</span>`).join(" ") || "—"}</dd>
          ${o.cancel_reason ? `<dt>${esc(t("cancel_reason"))}</dt><dd><span class="badge badge-red">${esc(o.cancel_reason_label || o.cancel_reason)}</span></dd>` : ""}
        </dl>
        ${o.status_key === "parts" ? partsBlock() : ""}
        <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-sm" id="btn-client-tg">${esc(t("tg_connect"))} (${esc(t("client_name"))})</button>
        </div>
      </div>
      <div class="panel">
        <h3>${esc(t("stage_executor"))}</h3>
        <table class="tbl">
          <thead><tr><th>${esc(t("f_status"))}</th><th>${esc(t("responsible"))}</th></tr></thead>
          <tbody>
            ${state.meta.statuses.map((s) => {
              const ex = (o.executors || {})[String(s.id)];
              return `<tr><td><span class="column-dot" style="background:${esc(s.color)};display:inline-block;margin-right:6px"></span>${esc(langOf(s))}</td>
                <td>${can("order.assign") ? `<select class="select sel-exec" data-status="${s.id}" style="width:auto">
                  <option value="">${esc(t("nobody"))}</option>
                  ${Object.entries(users).map(([uid, name]) => `<option value="${uid}" ${String(ex) === uid ? "selected" : ""}>${esc(name)}</option>`).join("")}
                </select>` : esc(users[String(ex)] || "—")}</td></tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>`;

  const btnEdit = qs("#btn-edit");
  if (btnEdit) btnEdit.onclick = editModal;
  const selResp = qs("#sel-resp");
  if (selResp) selResp.onchange = async () => {
    await api.post(`/api/orders/${order.id}/responsible`, { user_id: selResp.value ? parseInt(selResp.value, 10) : null });
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  };
  const selPrio = qs("#sel-prio");
  if (selPrio) selPrio.onchange = async () => {
    await api.post(`/api/orders/${order.id}/priority`, { priority: selPrio.value });
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  };
  qsa(".sel-exec").forEach((sel) => (sel.onchange = async () => {
    await api.post(`/api/orders/${order.id}/executor`, {
      status_id: parseInt(sel.dataset.status, 10),
      user_id: sel.value ? parseInt(sel.value, 10) : null,
    });
    toast(t("saved"), "success");
  }));
  qs("#btn-client-tg").onclick = clientTelegramModal;
  const saveParts = qs("#btn-parts");
  if (saveParts) saveParts.onclick = async () => {
    const val = qs("#parts-date").value;
    await api.put(`/api/orders/${order.id}/parts`, { expected_at: val ? new Date(val).toISOString() : null });
    toast(t("saved"), "success");
    await load(qs("#view"), order.id);
  };
}

function partsBlock() {
  const current = order.parts_expected_at
    ? new Date(order.parts_expected_at).toISOString().slice(0, 16)
    : "";
  return `
    <div class="panel" style="margin-top:12px;background:var(--panel-2)">
      <h3>${esc(t("parts_expected"))}</h3>
      ${order.parts_attention ? `<div class="alert alert-warn">${esc(t("parts_attention"))}</div>` : ""}
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
        <div class="field" style="flex:1;min-width:190px;margin:0">
          <input class="input" type="datetime-local" id="parts-date" value="${esc(current)}">
        </div>
        <button class="btn btn-primary btn-sm" id="btn-parts">${esc(t("parts_set"))}</button>
      </div>
    </div>`;
}

function editModal() {
  const o = order;
  const wrap = openModal({
    title: t("edit"),
    size: "lg",
    body: `
      <div class="form-row-3">
        <div class="field"><label>${esc(t("plate"))}</label><input class="input" id="e-plate" value="${esc(o.plate || "")}"></div>
        <div class="field"><label>${esc(t("vin"))}</label><input class="input" id="e-vin" value="${esc(o.vin || "")}"></div>
        <div class="field"><label>${esc(t("year"))}</label><input class="input" id="e-year" type="number" value="${esc(o.year || "")}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("make"))}</label><input class="input" id="e-make" value="${esc(o.make || "")}"></div>
        <div class="field"><label>${esc(t("model"))}</label><input class="input" id="e-model" value="${esc(o.model || "")}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("client_name"))}</label><input class="input" id="e-client" value="${esc(o.client_name || "")}"></div>
        <div class="field"><label>${esc(t("client_phone"))}</label><input class="input" id="e-phone" value="${esc(o.client_phone || "")}"></div>
      </div>
      <div class="field"><label>${esc(t("client_telegram"))}</label><input class="input" id="e-ctg" value="${esc(o.client_telegram || "")}"></div>
      <div class="field"><label>${esc(t("problem"))}</label><textarea class="textarea" id="e-problem">${esc(o.problem || "")}</textarea></div>
      <div class="form-row">
        <div class="field"><label>${esc(t("due_at"))}</label>
          <input class="input" id="e-due" type="datetime-local" value="${esc(o.due_at ? new Date(o.due_at).toISOString().slice(0, 16) : "")}"></div>
        <div class="field"><label>${esc(t("notes"))} (${esc(t("general_works"))})</label>
          <textarea class="textarea" id="e-works">${esc((o.original_works || []).join("\n"))}</textarea>
          <div class="hint">${esc(t("notes_line"))}</div></div>
      </div>
      <div class="field"><label>${esc(t("work_types"))}</label>
        <select class="select" id="e-wt" multiple size="4" style="height:auto">
          ${state.meta.work_types.filter((w) => w.active).map((w) => `<option value="${w.id}" ${o.work_type_ids.map(String).includes(String(w.id)) ? "selected" : ""}>${esc(langOf(w))}</option>`).join("")}
        </select></div>
      <div class="error-text" id="e-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="e-save">${esc(t("save"))}</button>`,
  });
  qs("#e-save", wrap).onclick = async () => {
    const payload = {
      plate: qs("#e-plate", wrap).value.trim(),
      vin: qs("#e-vin", wrap).value.trim(),
      make: qs("#e-make", wrap).value.trim(),
      model: qs("#e-model", wrap).value.trim(),
      year: qs("#e-year", wrap).value ? parseInt(qs("#e-year", wrap).value, 10) : null,
      client_name: qs("#e-client", wrap).value.trim(),
      client_phone: qs("#e-phone", wrap).value.trim(),
      client_telegram: qs("#e-ctg", wrap).value.trim(),
      problem: qs("#e-problem", wrap).value,
      due_at: qs("#e-due", wrap).value ? new Date(qs("#e-due", wrap).value).toISOString() : null,
      original_works: qs("#e-works", wrap).value.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    try {
      await api.put(`/api/orders/${order.id}`, payload);
      if (can("order.worktypes")) {
        const ids = qsa("#e-wt option", wrap).filter((x) => x.selected).map((x) => parseInt(x.value, 10));
        const same = JSON.stringify(ids.slice().sort()) === JSON.stringify(o.work_type_ids.slice().sort());
        if (!same) await api.post(`/api/orders/${order.id}/worktypes`, { ids });
      }
      closeModal();
      toast(t("saved"), "success");
      await load(qs("#view"), order.id);
    } catch (err) {
      qs("#e-err", wrap).textContent = err.message || t("error");
    }
  };
}

function clientTelegramModal() {
  const wrap = openModal({
    title: `${t("tg_connect")} — ${t("client_name")}`,
    size: "sm",
    body: `<div class="hint">${esc(t("tg_instruction"))}</div>
      <div class="field" style="margin-top:10px">
        <input class="input" id="ct-code" readonly value="—">
      </div>
      <div class="field"><input class="input" id="ct-link" readonly value="—"></div>
      ${order.client_binding && order.client_binding.bound_at
        ? `<div class="badge badge-green">✓ ${esc(t("tg_linked"))}</div>`
        : `<div class="badge badge-amber">${esc(t("tg_not_linked"))}</div>`}
      <div class="error-text" id="ct-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("close"))}</button>
             <button class="btn" id="ct-copy">${esc(t("tg_link_copy"))}</button>`,
  });
  api.post(`/api/orders/${order.id}/client-telegram/code`).then((data) => {
    qs("#ct-code", wrap).value = data.code;
    qs("#ct-link", wrap).value = data.link || t("tg_no_bot");
    if (!data.link) qs("#ct-err", wrap).textContent = t("tg_no_bot");
    qs("#ct-copy", wrap).onclick = () => copyText(data.link || data.code);
  }).catch((e) => { qs("#ct-err", wrap).textContent = e.message; });
}

/* ------------------------------------------------------------- works */
function tabWorks(host) {
  const o = order;
  const approvedMap = {};
  (o.approved_works || []).forEach((a) => (approvedMap[a.text] = a.state));
  const originals = o.original_works || [];
  const canApprove = can("order.approve") && o.status_key === "approval";

  host.innerHTML = `
    <div class="grid-2">
      <div class="panel">
        <h3>${esc(t("general_works"))}</h3>
        ${originals.length
          ? `<ol style="margin:0;padding-left:20px;font-size:14px">${originals.map((w) => `<li style="padding:3px 0">${esc(w)}</li>`).join("")}</ol>`
          : `<div class="hint">${esc(t("nothing"))}</div>`}
        ${can("order.edit") ? `<div style="margin-top:12px"><button class="btn btn-sm" id="w-edit">${esc(t("edit"))}</button></div>` : ""}
      </div>
      <div class="panel">
        <h3>${esc(t("approved_works"))}</h3>
        ${o.approval_state ? `<div class="badge badge-${o.approval_state === "full" ? "green" : o.approval_state === "rejected" ? "red" : "amber"}" style="margin-bottom:8px">${esc(approvalLabel(o.approval_state))}</div>` : `<div class="hint" style="margin-bottom:8px">${esc(t("approval_not_done"))}</div>`}
        ${(o.approved_works || []).length ? `
          <table class="tbl"><tbody>
          ${o.approved_works.map((a, idx) => `
            <tr>
              <td>${esc(a.text)}</td>
              <td style="width:150px">
                ${canApprove ? `<select class="select sel-appr" data-idx="${idx}">
                  <option value="approved" ${a.state === "approved" ? "selected" : ""}>${esc(t("state_approved"))}</option>
                  <option value="declined" ${a.state === "declined" ? "selected" : ""}>${esc(t("state_declined"))}</option>
                </select>` : `<span class="badge badge-${a.state === "approved" ? "green" : "red"}">${esc(a.state === "approved" ? t("state_approved") : t("state_declined"))}</span>`}
              </td>
            </tr>`).join("")}
          </tbody></table>` : `<div class="hint">${esc(t("nothing"))}</div>`}
        ${canApprove ? `
          <div class="hint" style="margin:12px 0 8px">${esc(t("approval_hint"))}</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary btn-sm" id="appr-all">${esc(t("approve_all"))}</button>
            <button class="btn btn-sm" id="appr-part">${esc(t("approve_partial"))}</button>
            <button class="btn btn-danger btn-sm" id="appr-rej">${esc(t("approve_reject"))}</button>
          </div>` : ""}
      </div>
    </div>
    ${can("order.worktypes") ? `
    <div class="panel">
      <h3>${esc(t("work_types"))}</h3>
      <div class="hint" style="margin-bottom:8px">${esc(t("work_types"))}: ${o.status_key === "appointment" ? "—" : ""}</div>
      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end">
        <div class="field" style="flex:1;min-width:220px;margin:0">
          <select class="select" id="wt-select" multiple size="5" style="height:auto" ${o.status_key === "appointment" ? "disabled" : ""}>
            ${state.meta.work_types.filter((w) => w.active).map((w) => `<option value="${w.id}" ${o.work_type_ids.map(String).includes(String(w.id)) ? "selected" : ""}>${esc(langOf(w))}</option>`).join("")}
          </select>
        </div>
        <button class="btn btn-primary btn-sm" id="wt-save" ${o.status_key === "appointment" ? "disabled" : ""}>${esc(t("save"))}</button>
      </div>
      ${o.status_key === "appointment" ? (() => {
        const diag = (state.meta.statuses || []).find((s) => s.key === "diagnostics")
          || { name_ru: "Диагностика", name_en: "Diagnostics" };
        return `<div class="hint" style="margin-top:8px">${esc(t("checklist_stage_hint", { status: langOf(diag) }))}</div>`;
      })() : ""}
    </div>` : ""}`;

  const wEdit = qs("#w-edit");
  if (wEdit) wEdit.onclick = editModal;
  const wtSave = qs("#wt-save");
  if (wtSave) wtSave.onclick = async () => {
    const ids = qsa("#wt-select option").filter((x) => x.selected).map((x) => parseInt(x.value, 10));
    try {
      await api.post(`/api/orders/${order.id}/worktypes`, { ids });
      toast(t("saved"), "success");
      await load(qs("#view"), order.id);
    } catch (e) { toast(e.message, "error"); }
  };

  async function sendApproval(decision) {
    const items = qsa(".sel-appr").length
      ? o.approved_works.map((a, i) => {
          const sel = qs(`.sel-appr[data-idx="${i}"]`);
          return { text: a.text, state: sel ? sel.value : a.state };
        })
      : originals.map((text) => ({ text, state: "approved" }));
    if (decision === "approved") items.forEach((i) => (i.state = "approved"));
    if (decision === "rejected") items.forEach((i) => (i.state = "declined"));
    try {
      await api.post(`/api/orders/${order.id}/approval`, { decision, items });
      toast(t("saved"), "success");
      await load(qs("#view"), order.id);
    } catch (e) {
      toast(e.message || t("error"), "error");
    }
  }
  const a1 = qs("#appr-all");
  if (a1) a1.onclick = () => sendApproval("approved");
  const a2 = qs("#appr-part");
  if (a2) a2.onclick = () => sendApproval("partial");
  const a3 = qs("#appr-rej");
  if (a3) a3.onclick = () => sendApproval("rejected");
}

/* ---------------------------------------------------------- checklist */
function tabChecklist(host) {
  const o = order;
  const items = o.checklist || [];
  const p = o.checklist_progress || { percent: 0, done: 0, total: 0 };
  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("tab_checklist"))}
        <span class="badge ${p.done === p.total && p.total ? "badge-green" : "badge-blue"}" style="margin-left:8px">${p.done}/${p.total} · ${p.percent}%</span>
        <div class="progress ${p.done === p.total && p.total ? "done" : ""}" style="margin-top:8px"><span style="width:${p.percent}%"></span></div>
      </h3>
      <div id="cl-list" style="margin-top:12px">
        ${items.length ? items.map(itemHtml).join("") : `<div class="hint">${esc(t("checklist_empty"))}</div>`}
      </div>
      ${can("order.checklist") ? `
      <div style="display:flex;gap:8px;margin-top:14px;align-items:flex-end;flex-wrap:wrap">
        <div class="field" style="flex:1;min-width:220px;margin:0">
          <input class="input" id="cl-new" placeholder="${esc(t("checklist_add"))}…">
        </div>
        <label class="checkbox"><input type="checkbox" id="cl-req" checked> ${esc(t("checklist_required"))}</label>
        <button class="btn btn-primary btn-sm" id="cl-add">${esc(t("add"))}</button>
      </div>` : ""}
    </div>`;

  qsa(".cl-check").forEach((cb) => (cb.onchange = async () => {
    try {
      const data = await api.post(`/api/orders/${order.id}/checklist/toggle`, {
        item_id: parseInt(cb.dataset.id, 10), done: cb.checked,
      });
      order.checklist = data.checklist;
      order.checklist_progress = data.progress;
      order.ready_problems = data.ready_problems;
      drawBanner();
      tabChecklist(host);
    } catch (e) { toast(e.message, "error"); }
  }));
  qsa(".cl-req").forEach((st) => (st.onclick = async () => {
    try {
      const data = await api.put(`/api/orders/${order.id}/checklist/item/${st.dataset.id}`, {
        required: !st.classList.contains("on"),
      });
      order.checklist = data.checklist;
      tabChecklist(host);
    } catch (e) { toast(e.message, "error"); }
  }));
  qsa(".cl-del").forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    try {
      const data = await api.del(`/api/orders/${order.id}/checklist/item/${b.dataset.id}`);
      order.checklist = data.checklist;
      tabChecklist(host);
    } catch (e) { toast(e.message, "error"); }
  }));
  const add = qs("#cl-add");
  if (add) add.onclick = async () => {
    const text = qs("#cl-new").value.trim();
    if (!text) return;
    try {
      const data = await api.post(`/api/orders/${order.id}/checklist/item`, {
        text, required: qs("#cl-req").checked,
      });
      order.checklist = data.checklist;
      order.checklist_progress = data.progress;
      tabChecklist(host);
    } catch (e) { toast(e.message, "error"); }
  };
}

function itemHtml(i) {
  const doneBy = i.done && i.done_at ? `${i.done_by ? "" : ""}${fmtDateTime(i.done_at)}` : "";
  return `
  <div class="checklist-item ${i.done ? "done" : ""}">
    ${can("order.checklist") ? `<input type="checkbox" class="cl-check" data-id="${i.id}" ${i.done ? "checked" : ""}>` : `<span>${i.done ? "✓" : "○"}</span>`}
    <div class="ctext">
      <span>${esc(i.text)}</span>
      ${i.stage_key ? `<span class="cstage">${esc(stageLabel(i.stage_key))}</span>` : ""}
      ${i.required ? `<span class="star" title="${esc(t("checklist_required"))}">★</span>` : ""}
      ${doneBy ? `<div class="cdone">${esc(doneBy)}</div>` : ""}
    </div>
    <span class="star cl-req ${i.required ? "on" : ""}" data-id="${i.id}" title="${esc(t("checklist_required"))}" style="${can("order.checklist.required") ? "" : "visibility:hidden"}">${i.required ? "★" : "☆"}</span>
    ${can("order.checklist") ? `<button class="icon-btn cl-del" data-id="${i.id}" title="${esc(t("delete"))}" style="width:26px;height:26px">✕</button>` : ""}
  </div>`;
}

function stageLabel(key) {
  const st = state.meta.statuses.find((s) => s.key === key);
  return st ? langOf(st) : key;
}

/* ---------------------------------------------------------------- time */
function tabTime(host) {
  const tm = order.time || {};
  const statuses = state.meta.statuses;
  const sName = (key) => {
    const st = statuses.find((s) => s.key === key);
    return st ? langOf(st) : key;
  };
  host.innerHTML = `
    <div class="grid-4">
      <div class="stat-card"><div class="s-label">${esc(t("t_total"))}</div><div class="s-value" style="font-size:20px">${esc(fmtDuration(tm.total_seconds))}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("t_working"))}</div><div class="s-value" style="font-size:20px">${esc(fmtDuration(tm.working_seconds))}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("t_waiting"))}</div><div class="s-value" style="font-size:20px">${esc(fmtDuration(tm.waiting_seconds))}</div></div>
      <div class="stat-card"><div class="s-label">${esc(t("t_pause"))}</div><div class="s-value" style="font-size:20px">${esc(fmtDuration(tm.pause_seconds))}</div></div>
    </div>
    <div class="grid-2" style="margin-top:14px">
      <div class="panel">
        <h3>${esc(t("t_stages"))}</h3>
        <table class="tbl">
          <thead><tr><th>${esc(t("f_status"))}</th><th>${esc(t("duration"))}</th></tr></thead>
          <tbody>
            ${Object.entries(tm.stage_seconds || {}).map(([k, v]) => `<tr><td>${esc(sName(k))}</td><td>${esc(fmtDuration(v))}</td></tr>`).join("") || `<tr><td colspan="2" class="hint">${esc(t("nothing"))}</td></tr>`}
          </tbody>
        </table>
        <div style="margin-top:12px">
          ${tm.active_pause
            ? `<span class="badge badge-amber">${esc(t("paused"))}</span>`
            : ""}
          ${can("order.move") || can("order.edit") ? `<button class="btn btn-sm ${tm.active_pause ? "btn-primary" : ""}" id="btn-pause" style="margin-left:8px">${esc(tm.active_pause ? t("pause_end") : t("pause_start"))}</button>` : ""}
        </div>
      </div>
      <div class="panel">
        <h3>${esc(t("t_intervals"))}</h3>
        <table class="tbl">
          <thead><tr><th>${esc(t("f_status"))}</th><th>${esc(t("started"))}</th><th>${esc(t("ended"))}</th></tr></thead>
          <tbody>
            ${(tm.intervals || []).slice().reverse().map((iv) => `
              <tr>
                <td>${esc(sName(iv.status_key))}</td>
                <td>${esc(fmtDateTime(iv.started_at))}</td>
                <td>${iv.ended_at ? esc(fmtDuration(iv.seconds)) : `<span class="badge badge-blue">${esc(t("running"))}</span>`}</td>
              </tr>`).join("") || `<tr><td colspan="3" class="hint">${esc(t("nothing"))}</td></tr>`}
          </tbody>
        </table>
        ${(tm.pauses || []).length ? `
          <h3 style="margin-top:14px">${esc(t("t_pause"))}</h3>
          <table class="tbl"><tbody>
            ${tm.pauses.slice().reverse().map((p) => `<tr><td>${esc(fmtDateTime(p.started_at))}</td><td>${p.ended_at ? esc(fmtDateTime(p.ended_at)) : "…"}</td><td>${esc(fmtDuration(p.seconds))}</td></tr>`).join("")}
          </tbody></table>` : ""}
      </div>
    </div>`;
  const btn = qs("#btn-pause");
  if (btn) btn.onclick = async () => {
    const data = await api.post(`/api/orders/${order.id}/pause`);
    order.time = data.time;
    tabTime(host);
  };
}

/* ------------------------------------------------------------ comments */
function tabComments(host) {
  const comments = order.comments || [];
  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("tab_comments"))}</h3>
      <div id="c-list">
        ${comments.length ? comments.map(commentHtml).join("") : `<div class="hint">${esc(t("no_comments"))}</div>`}
      </div>
      ${can("order.comment") ? `
      <div style="display:flex;gap:8px;margin-top:14px">
        <textarea class="textarea" id="c-new" placeholder="${esc(t("comment_placeholder"))}" style="flex:1"></textarea>
        <button class="btn btn-primary" id="c-send">${esc(t("send"))}</button>
      </div>` : ""}
    </div>`;
  const send = qs("#c-send");
  if (send) send.onclick = async () => {
    const text = qs("#c-new").value.trim();
    if (!text) return;
    try {
      const data = await api.post(`/api/orders/${order.id}/comments`, { text });
      order.comments = data.comments;
      tabComments(host);
    } catch (e) { toast(e.message, "error"); }
  };
  qsa(".c-edit").forEach((b) => (b.onclick = () => editComment(b.dataset.id, host)));
  qsa(".c-del").forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog(t("delete_confirm"), { danger: true, okLabel: t("delete") }))) return;
    const data = await api.del(`/api/orders/${order.id}/comments/${b.dataset.id}`);
    order.comments = data.comments;
    tabComments(host);
  }));
}

function commentHtml(c) {
  const mine = c.user_id === state.user.id;
  const canMod = mine || can("order.comment.moderate");
  return `
  <div class="comment">
    <div class="avatar">${esc((c.full_name || c.login || "?").split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase())}</div>
    <div class="cbody">
      <div class="cmeta">${esc(c.full_name || c.login)} · ${esc(fmtDateTime(c.created_at))}${c.edited_at ? " · ✎" : ""}</div>
      <div class="ctext2">${esc(c.text)}</div>
    </div>
    ${canMod ? `<div style="display:flex;gap:4px">
      <button class="icon-btn c-edit" data-id="${c.id}" style="width:26px;height:26px" title="${esc(t("edit"))}">✎</button>
      <button class="icon-btn c-del" data-id="${c.id}" style="width:26px;height:26px" title="${esc(t("delete"))}">✕</button>
    </div>` : ""}
  </div>`;
}

async function editComment(id, host) {
  const c = (order.comments || []).find((x) => x.id === parseInt(id, 10));
  if (!c) return;
  const wrap = openModal({
    title: t("edit_comment"),
    body: `<textarea class="textarea" id="ec-text">${esc(c.text)}</textarea>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="ec-save">${esc(t("save"))}</button>`,
  });
  qs("#ec-save", wrap).onclick = async () => {
    const data = await api.put(`/api/orders/${order.id}/comments/${id}`, { text: qs("#ec-text", wrap).value });
    order.comments = data.comments;
    closeModal();
    tabComments(host);
  };
}

/* ------------------------------------------------------------- history */
function tabHistory(host) {
  const rows = order.history || [];
  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("tab_history"))}</h3>
      <div class="timeline">
        ${rows.map((h) => `
          <div class="tl-item">
            <div><b>${esc(actionLabel(h.action))}</b>${h.field ? ` · ${esc(h.field)}` : ""}
              ${h.old_value || h.new_value ? `<span class="tl-time">(${esc(t("old_value"))}: ${esc(short(h.old_value))} → ${esc(t("new_value"))}: ${esc(short(h.new_value))})</span>` : ""}</div>
            <div class="tl-time">${esc(h.full_name || h.login || t("nobody"))} · ${esc(fmtDateTime(h.created_at))}</div>
          </div>`).join("") || `<div class="hint">${esc(t("nothing"))}</div>`}
      </div>
    </div>`;
}

function short(v) {
  if (v === null || v === undefined || v === "") return "—";
  const s = String(v);
  return s.length > 60 ? s.slice(0, 60) + "…" : s;
}

function actionLabel(action) {
  const map = {
    created: "h_created", status_change: "h_status_change", field: "h_field",
    assign: "h_assign", priority: "h_priority", due: "h_due", work_types: "h_work_types",
    comment: "h_comment", checklist_toggle: "h_checklist_toggle", checklist_add: "h_checklist_add",
    checklist_edit: "h_checklist_edit", checklist_delete: "h_checklist_delete",
    checklist_required: "h_checklist_required", approval: "h_approval", archive: "h_archive",
    delete: "h_delete", restore: "h_restore", duplicated: "h_duplicated", vin_merged: "h_vin_merged",
    pause_start: "h_pause_start", pause_end: "h_pause_end", parts_expected: "h_parts_expected",
    executor: "h_executor", parts_attention: "h_parts_attention",
  };
  return t(map[action] || action);
}

/* ------------------------------------------------------------------ vin */
function tabVin(host) {
  const hist = order.vin_history || [];
  const plates = order.plates || [];
  host.innerHTML = `
    <div class="panel">
      <h3>${esc(t("history_of_vin"))}</h3>
      ${order.vin ? `<div class="alert alert-info">VIN: <b>${esc(order.vin)}</b></div>` : `<div class="alert alert-warn">${esc(t("p_vin_required"))}</div>`}
      <table class="tbl">
        <thead><tr>
          <th>${esc(t("order"))}</th><th>${esc(t("visit_date"))}</th><th>${esc(t("plate"))}</th>
          <th>${esc(t("make"))}</th><th>${esc(t("client_name"))}</th><th>${esc(t("problem"))}</th>
          <th>${esc(t("responsible"))}</th><th>${esc(t("f_status"))}</th><th></th>
        </tr></thead>
        <tbody>
          ${hist.map((h) => `
            <tr ${h.id === order.id ? 'style="background:var(--brand-soft)"' : ""}>
              <td><b>${esc(h.number)}</b></td>
              <td>${esc(fmtDate(h.created_at))}</td>
              <td>${esc(h.plate || "—")}</td>
              <td>${esc([h.make, h.model].filter(Boolean).join(" "))}</td>
              <td>${esc(h.client_name || "—")}</td>
              <td>${esc(short(h.problem))}</td>
              <td>${esc(h.responsible || "—")}</td>
              <td>${esc(h.status_ru || "")}</td>
              <td>${h.id !== order.id ? `<button class="btn btn-sm" data-open="${h.id}">${esc(t("open_order"))}</button>` : ""}</td>
            </tr>`).join("") || `<tr><td colspan="9" class="hint">${esc(t("nothing"))}</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>${esc(t("plate_history"))}</h3>
      <table class="tbl">
        <thead><tr><th>${esc(t("plate"))}</th><th>${esc(t("visit_date"))}</th></tr></thead>
        <tbody>
          ${plates.map((p) => `<tr><td><b>${esc(p.plate_raw)}</b></td><td>${esc(fmtDate(p.first_seen_at))}</td></tr>`).join("") || `<tr><td colspan="2" class="hint">${esc(t("nothing"))}</td></tr>`}
        </tbody>
      </table>
    </div>`;
  qsa("[data-open]", host).forEach((b) => (b.onclick = () => navigate("#/order/" + b.dataset.open)));
}
