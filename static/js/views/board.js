import * as api from "../api.js";
import { t, nameOf as langOf } from "../i18n.js";
import {
  esc, qs, qsa, toast, openModal, closeModal, debounce, fmtDate, isOverdue, confirmDialog,
} from "../ui.js";
import { state, can, navigate, icon } from "../app.js";

const filters = {
  q: "", mine: false, responsible: "", priority: "", overdue: false,
  due_from: "", due_to: "", work_type: "", created_from: "", created_to: "",
  archive: false, filtersOpen: false,
};

let boardData = null;

export async function renderBoard(container) {
  if (sessionStorage.getItem("board_q") !== null) {
    filters.q = sessionStorage.getItem("board_q") || "";
    sessionStorage.removeItem("board_q");
  }
  container.innerHTML = `
    <div class="board-toolbar">
      <div class="top-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="board-search" placeholder="${esc(t("search_placeholder"))}" value="${esc(filters.q)}">
      </div>
      <button class="chip ${filters.mine ? "active" : ""}" id="chip-mine">${esc(t("only_mine"))}</button>
      <button class="chip ${filters.overdue ? "active" : ""}" id="chip-overdue">${esc(t("f_overdue"))}</button>
      <button class="chip ${filters.filtersOpen ? "active" : ""}" id="chip-filters">${icon("filter")} ${esc(t("filters"))}</button>
      <button class="chip ${filters.archive ? "active" : ""}" id="chip-archive">${esc(t("archive_view"))}</button>
      <div style="flex:1"></div>
      ${can("order.create") ? `<button class="btn btn-primary btn-sm" id="btn-new">${icon("plus")}<span class="btn-label">${esc(t("new_order"))}</span></button>` : ""}
    </div>
    <div class="filters-panel" id="filters-panel" style="display:${filters.filtersOpen ? "grid" : "none"}">
      <div class="field"><label>${esc(t("f_responsible"))}</label>
        <select class="select" id="f-responsible"></select></div>
      <div class="field"><label>${esc(t("f_priority"))}</label>
        <select class="select" id="f-priority">
          <option value="">${esc(t("f_any"))}</option>
          <option value="normal">${esc(t("prio_normal"))}</option>
          <option value="urgent">${esc(t("prio_urgent"))}</option>
          <option value="critical">${esc(t("prio_critical"))}</option>
        </select></div>
      <div class="field"><label>${esc(t("f_work_type"))}</label>
        <select class="select" id="f-worktype"></select></div>
      <div class="field"><label>${esc(t("f_due_from"))}</label><input type="date" class="input" id="f-due-from"></div>
      <div class="field"><label>${esc(t("f_due_to"))}</label><input type="date" class="input" id="f-due-to"></div>
      <div class="field"><label>${esc(t("f_created_from"))}</label><input type="date" class="input" id="f-created-from"></div>
      <div class="field"><label>${esc(t("f_created_to"))}</label><input type="date" class="input" id="f-created-to"></div>
      <div class="field"><label>&nbsp;</label><button class="btn btn-block" id="f-reset">${esc(t("reset_filters"))}</button></div>
    </div>
    <div class="board" id="board"><div style="margin:auto;color:var(--muted)"><div class="spinner"></div></div></div>`;

  wireToolbar(container);
  await loadBoard();
}

function wireToolbar(root) {
  const search = qs("#board-search", root);
  search.addEventListener("input", debounce(async () => {
    filters.q = search.value;
    await loadBoard();
  }, 320));
  qs("#chip-mine", root).onclick = async () => { filters.mine = !filters.mine; await renderBoard(root); };
  qs("#chip-overdue", root).onclick = async () => { filters.overdue = !filters.overdue; await renderBoard(root); };
  qs("#chip-archive", root).onclick = async () => { filters.archive = !filters.archive; await renderBoard(root); };
  qs("#chip-filters", root).onclick = async () => { filters.filtersOpen = !filters.filtersOpen; await renderBoard(root); };
  const btnNew = qs("#btn-new", root);
  if (btnNew) btnNew.onclick = () => openCreateModal(() => loadBoard());

  const resp = qs("#f-responsible", root);
  resp.innerHTML = `<option value="">${esc(t("f_any"))}</option>` +
    (boardData ? boardData.users : state.meta.users)
      .map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("") +
    `<option value="none">${esc(t("nobody"))}</option>`;
  const wt = qs("#f-worktype", root);
  wt.innerHTML = `<option value="">${esc(t("f_any"))}</option>` +
    (boardData ? boardData.work_types : state.meta.work_types)
      .map((w) => `<option value="${w.id}">${esc(langOf(w))}</option>`).join("");

  resp.value = filters.responsible;
  wt.value = filters.work_type;
  qs("#f-priority", root).value = filters.priority;
  qs("#f-due-from", root).value = filters.due_from;
  qs("#f-due-to", root).value = filters.due_to;
  qs("#f-created-from", root).value = filters.created_from;
  qs("#f-created-to", root).value = filters.created_to;

  resp.onchange = async () => { filters.responsible = resp.value; await loadBoard(); };
  wt.onchange = async () => { filters.work_type = wt.value; await loadBoard(); };
  qs("#f-priority", root).onchange = async (e) => { filters.priority = e.target.value; await loadBoard(); };
  qs("#f-due-from", root).onchange = async (e) => { filters.due_from = e.target.value; await loadBoard(); };
  qs("#f-due-to", root).onchange = async (e) => { filters.due_to = e.target.value; await loadBoard(); };
  qs("#f-created-from", root).onchange = async (e) => { filters.created_from = e.target.value; await loadBoard(); };
  qs("#f-created-to", root).onchange = async (e) => { filters.created_to = e.target.value; await loadBoard(); };
  qs("#f-reset", root).onclick = async () => {
    Object.assign(filters, {
      q: "", mine: false, responsible: "", priority: "", overdue: false,
      due_from: "", due_to: "", work_type: "", created_from: "", created_to: "",
    });
    await renderBoard(root);
  };
}

function queryParams() {
  return api.qs({
    q: filters.q, mine: filters.mine ? 1 : "", responsible: filters.responsible,
    priority: filters.priority, overdue: filters.overdue ? 1 : "",
    due_from: filters.due_from ? filters.due_from + "T00:00:00.000Z" : "",
    due_to: filters.due_to ? filters.due_to + "T23:59:59.999Z" : "",
    work_type: filters.work_type,
    created_from: filters.created_from ? filters.created_from + "T00:00:00.000Z" : "",
    created_to: filters.created_to ? filters.created_to + "T23:59:59.999Z" : "",
    archive: filters.archive ? 1 : "",
  });
}

async function loadBoard() {
  boardData = await api.get("/api/board" + queryParams());
  drawBoard();
}

function drawBoard() {
  const host = qs("#board");
  if (!host) return;
  const { statuses, orders } = boardData;
  const visible = statuses.filter((s) => filters.archive || !s.hidden);
  host.innerHTML = visible
    .map((st) => {
      const cards = orders.filter((o) => o.status_id === st.id);
      return `
      <section class="column" data-status="${st.id}">
        <header class="column-head">
          <span class="column-dot" style="background:${esc(st.color)}"></span>
          <span>${esc(langOf(st))}</span>
          <span class="column-count">${cards.length}</span>
        </header>
        <div class="column-body" data-drop="${st.id}">
          ${cards.map(cardHtml).join("") || `<div class="hint" style="padding:8px 4px">${esc(t("no_cards"))}</div>`}
        </div>
      </section>`;
    })
    .join("");
  wireBoard(host);
}

function cardHtml(o) {
  const late = isOverdue(o);
  const prog = o.checklist || { percent: 0, done: 0, total: 0 };
  return `
  <article class="card ${late ? "overdue" : ""} ${o.parts_attention ? "attention" : ""}"
     draggable="${can("order.move")}" data-id="${o.id}" data-version="1">
    <div class="card-top">
      <span class="card-plate">${esc(o.plate || "—")}</span>
      <span class="prio prio-${o.priority}">${esc(t("prio_" + o.priority))}</span>
    </div>
    <div class="card-car">${esc([o.make, o.model].filter(Boolean).join(" ") || "—")}${o.client_name ? " · " + esc(o.client_name) : ""}</div>
    <div class="card-meta">
      <span class="who">${icon("user")} ${esc(o.responsible_name || t("nobody"))}</span>
      ${late ? `<span class="mini-icon" style="color:var(--danger);font-weight:600">⚠ ${esc(t("overdue"))}</span>` : ""}
      ${o.parts_attention ? `<span class="mini-icon" style="color:var(--warning);font-weight:600">⚠ ${esc(t("attention"))}</span>` : ""}
    </div>
    ${o.due_at ? `<div class="card-due ${late ? "late" : ""}">${esc(t("due"))}: ${esc(fmtDate(o.due_at))}</div>` : ""}
    ${prog.total ? `<div class="progress ${prog.done === prog.total ? "done" : ""}"><span style="width:${prog.percent}%"></span></div>
      <div class="hint" style="margin-top:4px">${esc(t("checklist_progress"))}: ${prog.done}/${prog.total}</div>` : ""}
  </article>`;
}

function wireBoard(host) {
  qsa(".card", host).forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("input")) return;
      navigate("#/order/" + card.dataset.id);
    });
    card.addEventListener("dragstart", (e) => {
      card.classList.add("dragging");
      e.dataTransfer.setData("text/plain", card.dataset.id);
      e.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
  });
  qsa(".column", host).forEach((col) => {
    const body = qs(".column-body", col);
    col.addEventListener("dragover", (e) => {
      e.preventDefault();
      col.classList.add("drop-target");
    });
    col.addEventListener("dragleave", (e) => {
      if (!col.contains(e.relatedTarget)) col.classList.remove("drop-target");
    });
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drop-target");
      const id = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const statusId = parseInt(col.dataset.status, 10);
      if (!id || !statusId) return;
      await moveOrder(id, statusId);
    });
  });
}

async function moveOrder(id, statusId, extra = {}) {
  try {
    await api.post(`/api/orders/${id}/move`, { status_id: statusId, ...extra });
    toast(t("saved"), "success");
    await loadBoard();
  } catch (err) {
    if (err.code === "ready_conditions") return showReadyProblems(id, statusId, err.data.problems || []);
    if (err.code === "cancel_reason_required") return showCancelDialog(id, statusId);
    if (err.code === "version_conflict") {
      toast(t("version_conflict"), "error");
      await loadBoard();
      return;
    }
    toast(err.message || t("error"), "error");
  }
}

function showCancelDialog(id, statusId) {
  const reasons = (state.meta && state.meta.cancel_reasons) || [];
  const wrap = openModal({
    title: t("cancel_title"),
    size: "sm",
    body: `
      <div class="field">
        <label>${esc(t("cancel_reason"))} <span class="req">*</span></label>
        <select class="select" id="cancel-reason">
          <option value="">${esc(t("select_value"))}</option>
          ${reasons.map((r) => `<option value="${esc(r.key)}">${esc(r.ru || r.key)}</option>`).join("")}
        </select>
      </div>
      <div class="error-text" id="cancel-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-danger" id="cancel-go">${esc(t("cancel_order"))}</button>`,
  });
  qs("#cancel-go", wrap).onclick = async () => {
    const reason = qs("#cancel-reason", wrap).value;
    if (!reason) {
      qs("#cancel-err", wrap).textContent = t("cancel_required");
      return;
    }
    closeModal();
    await moveOrder(id, statusId, { reason });
  };
}

function showReadyProblems(orderId, statusId, problems) {
  const hasConflict = problems.some((p) => p.code === "vin_conflict");
  if (hasConflict) return showVinConflict(orderId, statusId, problems.find((p) => p.code === "vin_conflict"));

  const items = problems
    .map((p) => {
      let text = t("p_" + p.code);
      if (p.code === "checklist_incomplete" && p.items) {
        text += "<ul style='margin:6px 0 0 16px;padding:0'>" +
          p.items.map((i) => `<li>${esc(i)}</li>`).join("") + "</ul>";
      }
      return `<li style="margin-bottom:6px">${text}</li>`;
    })
    .join("");

  const wrap = openModal({
    title: t("ready_blocked"),
    body: `<ul style="margin:0 0 12px;padding-left:18px">${items}</ul>
           <div class="hint">${esc(t("ready_ok"))} ${esc(t("ready_retry"))}</div>`,
    footer: `<button class="btn" data-close>${esc(t("close"))}</button>
             <button class="btn btn-primary" id="go-order">${esc(t("open_order"))}</button>`,
  });
  qs("#go-order", wrap).onclick = () => {
    closeModal();
    navigate("#/order/" + orderId);
  };
}

function showVinConflict(orderId, statusId, problem) {
  const history = problem.history || [];
  const wrap = openModal({
    title: t("p_vin_conflict"),
    body: `
      <div class="alert alert-warn">${esc(t("history_of_vin"))}: <b>${esc(problem.history?.[0]?.vin || "")}</b></div>
      ${history.map((h) => `
        <div class="candidate">
          <div class="cinfo">
            <div class="cplate">${esc(h.plate || "—")} · ${esc(h.number)}</div>
            <div class="csub">${esc([h.make, h.model].filter(Boolean).join(" "))} · ${esc(h.client_name || "")}</div>
            <div class="cdate">${esc(t("visit_date"))}: ${esc(fmtDate(h.created_at))} · ${esc(h.status_ru || "")}</div>
          </div>
        </div>`).join("")}`,
    footer: `
      <button class="btn" data-close>${esc(t("cancel"))}</button>
      <button class="btn" id="vin-edit">${esc(t("merge_edit_vin"))}</button>
      <button class="btn btn-primary" id="vin-merge">${esc(t("merge_confirm"))}</button>`,
  });
  qs("#vin-merge", wrap).onclick = async () => {
    closeModal();
    await moveOrder(orderId, statusId, { accept_vin_merge: true });
  };
  qs("#vin-edit", wrap).onclick = () => {
    closeModal();
    navigate("#/order/" + orderId);
  };
}

/* ========================================================== create modal */
export function openCreateModal(onCreated, prefill = {}) {
  const meta = state.meta;
  const platesBlock = `
    <div class="field">
      <label>${esc(t("plate"))} <span class="req">*</span></label>
      <input class="input" id="co-plate" value="${esc(prefill.plate || "")}" placeholder="А123АА77" autocomplete="off">
      <div class="hint" id="co-plate-info"></div>
    </div>
    <div id="co-candidates"></div>`;

  const wrap = openModal({
    title: t("create_order"),
    size: "lg",
    body: `
      <div class="form-row">${platesBlock}</div>
      <div class="form-row-3">
        <div class="field"><label>${esc(t("vin"))}</label><input class="input" id="co-vin" value="${esc(prefill.vin || "")}"></div>
        <div class="field"><label>${esc(t("make"))}</label><input class="input" id="co-make" value="${esc(prefill.make || "")}"></div>
        <div class="field"><label>${esc(t("model"))}</label><input class="input" id="co-model" value="${esc(prefill.model || "")}"></div>
      </div>
      <div class="form-row-3">
        <div class="field"><label>${esc(t("year"))}</label><input class="input" id="co-year" type="number" min="1950" max="2100" value="${esc(prefill.year || "")}"></div>
        <div class="field"><label>${esc(t("client_name"))}</label><input class="input" id="co-client" value="${esc(prefill.client_name || "")}"></div>
        <div class="field"><label>${esc(t("client_phone"))}</label><input class="input" id="co-phone" value="${esc(prefill.client_phone || "")}"></div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("client_telegram"))}</label><input class="input" id="co-ctg" value="${esc(prefill.client_telegram || "")}"></div>
        <div class="field"><label>${esc(t("priority"))}</label>
          <select class="select" id="co-priority">
            <option value="normal">${esc(t("prio_normal"))}</option>
            <option value="urgent">${esc(t("prio_urgent"))}</option>
            <option value="critical">${esc(t("prio_critical"))}</option>
          </select></div>
      </div>
      <div class="field"><label>${esc(t("problem"))}</label>
        <textarea class="textarea" id="co-problem">${esc(prefill.problem || "")}</textarea></div>
      <div class="form-row">
        <div class="field"><label>${esc(t("work_types"))}</label>
          <select class="select" id="co-wt" multiple size="4" style="height:auto">
            ${meta.work_types.filter((w) => w.active).map((w) => `<option value="${w.id}">${esc(langOf(w))}</option>`).join("")}
          </select></div>
        <div>
          <div class="field"><label>${esc(t("responsible"))}</label>
            <select class="select" id="co-resp">
              <option value="">${esc(t("nobody"))}</option>
              ${meta.users.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}
            </select></div>
          <div class="field"><label>${esc(t("due_at"))}</label>
            <input class="input" id="co-due" type="datetime-local"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="field"><label>${esc(t("template"))}</label>
          <select class="select" id="co-template">
            <option value="">${esc(t("f_any"))}</option>
            ${(meta.card_templates || []).map((tpl) => `<option value="${tpl.id}">${esc(tpl.name)}</option>`).join("")}
          </select></div>
        <div class="field"><label>${esc(t("from_order"))}</label>
          <input class="input" id="co-from" type="number" placeholder="${esc(t("from_order_hint"))}" value="${esc(prefill.source_order_id || "")}"></div>
      </div>
      <div class="error-text" id="co-err"></div>`,
    footer: `
      <button class="btn" data-close>${esc(t("cancel"))}</button>
      <button class="btn btn-primary" id="co-submit">${esc(t("create_btn"))}</button>`,
  });

  let choice = null; // {vehicle_id} | {no_merge:true}
  if (prefill.vehicle_id) choice = { vehicle_id: prefill.vehicle_id };

  const plateInput = qs("#co-plate", wrap);
  const info = qs("#co-plate-info", wrap);
  const candHost = qs("#co-candidates", wrap);

  function renderCandidates(list) {
    if (!list.length) {
      candHost.innerHTML = "";
      choice = { no_merge: true };
      info.textContent = "";
      return;
    }
    choice = null;
    info.textContent = t("merge_title");
    candHost.innerHTML = `
      <div class="hint" style="margin-bottom:6px">${esc(t("merge_sub"))}</div>
      ${list.map((c) => `
        <div class="candidate">
          <div class="cinfo">
            <div class="cplate">${esc(c.plate)}</div>
            <div class="csub">${esc([c.make, c.model].filter(Boolean).join(" "))} · VIN: ${esc(c.vin || "—")}</div>
            <div class="csub">${esc(c.client_name || "—")} · ${esc(c.client_phone || "")}</div>
            <div class="cdate">${esc(t("last_visit"))}: ${esc(fmtDate(c.last_visit))} · ${esc(t("orders_count"))}: ${c.orders_count}</div>
          </div>
          <button class="btn btn-sm btn-primary" data-vehicle="${c.vehicle_id}">${esc(t("merge_choose"))}</button>
        </div>`).join("")}
      <button class="btn btn-sm" id="co-no-merge">${esc(t("no_merge"))}</button>`;
    qsa("[data-vehicle]", candHost).forEach((b) => (b.onclick = () => {
      choice = { vehicle_id: parseInt(b.dataset.vehicle, 10) };
      candHost.querySelectorAll(".candidate").forEach((c) => (c.style.opacity = ".5"));
      b.closest(".candidate").style.opacity = "1";
      b.textContent = "✓ " + t("merge_choose");
      qs("#co-err", wrap).textContent = "";
    }));
    qs("#co-no-merge", candHost).onclick = () => {
      choice = { no_merge: true };
      candHost.innerHTML = `<div class="badge badge-blue">${esc(t("no_merge"))} ✓</div>`;
    };
  }

  const search = debounce(async () => {
    const plate = plateInput.value.trim();
    if (plate.length < 3) {
      candHost.innerHTML = "";
      choice = plate ? null : null;
      info.textContent = "";
      if (!plate) choice = { no_merge: true };
      return;
    }
    info.textContent = t("plate_searching");
    try {
      const data = await api.get("/api/orders/search-plate" + api.qs({ plate }));
      renderCandidates(data.candidates || []);
    } catch (e) {
      info.textContent = "";
    }
  }, 350);

  plateInput.addEventListener("input", () => {
    if (!plateInput.value.trim()) {
      candHost.innerHTML = "";
      info.textContent = "";
      choice = { no_merge: true };
      return;
    }
    search();
  });
  if (prefill.plate) search();
  else choice = { no_merge: true };

  qs("#co-from", wrap).addEventListener("change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    try {
      const data = await api.get("/api/orders/prefill" + api.qs({ from_order_id: id }));
      const p = data.prefill || {};
      if (p.plate) qs("#co-plate", wrap).value = p.plate;
      if (p.vin) qs("#co-vin", wrap).value = p.vin;
      if (p.make) qs("#co-make", wrap).value = p.make;
      if (p.model) qs("#co-model", wrap).value = p.model;
      if (p.year) qs("#co-year", wrap).value = p.year;
      if (p.client_name) qs("#co-client", wrap).value = p.client_name;
      if (p.client_phone) qs("#co-phone", wrap).value = p.client_phone;
      if (p.problem) qs("#co-problem", wrap).value = p.problem;
      if (p.priority) qs("#co-priority", wrap).value = p.priority;
      if (p.work_type_ids) {
        qsa("#co-wt option", wrap).forEach((o) => {
          o.selected = p.work_type_ids.map(String).includes(o.value);
        });
      }
      if (p.plate) search();
      toast(t("saved"), "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  qs("#co-template", wrap).addEventListener("change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    try {
      const data = await api.get("/api/orders/prefill" + api.qs({ template_id: id }));
      const p = data.prefill || {};
      if (p.problem) qs("#co-problem", wrap).value = p.problem;
      if (p.make) qs("#co-make", wrap).value = p.make;
      if (p.model) qs("#co-model", wrap).value = p.model;
      if (p.year) qs("#co-year", wrap).value = p.year;
      if (p.priority) qs("#co-priority", wrap).value = p.priority;
      if (p.work_type_ids) {
        qsa("#co-wt option", wrap).forEach((o) => {
          o.selected = p.work_type_ids.map(String).includes(o.value);
        });
      }
    } catch (err) {
      toast(err.message, "error");
    }
  });

  qs("#co-submit", wrap).onclick = async () => {
    const errHost = qs("#co-err", wrap);
    errHost.textContent = "";
    const plate = plateInput.value.trim();
    if (!plate) {
      errHost.textContent = t("plate_required");
      plateInput.focus();
      return;
    }
    if (!choice) {
      errHost.textContent = t("merge_choice_required");
      return;
    }
    const payload = {
      plate,
      vin: qs("#co-vin", wrap).value.trim(),
      make: qs("#co-make", wrap).value.trim(),
      model: qs("#co-model", wrap).value.trim(),
      year: qs("#co-year", wrap).value ? parseInt(qs("#co-year", wrap).value, 10) : null,
      client_name: qs("#co-client", wrap).value.trim(),
      client_phone: qs("#co-phone", wrap).value.trim(),
      client_telegram: qs("#co-ctg", wrap).value.trim(),
      problem: qs("#co-problem", wrap).value.trim(),
      priority: qs("#co-priority", wrap).value,
      responsible_id: qs("#co-resp", wrap).value ? parseInt(qs("#co-resp", wrap).value, 10) : null,
      due_at: qs("#co-due", wrap).value ? new Date(qs("#co-due", wrap).value).toISOString() : null,
      work_type_ids: qsa("#co-wt option", wrap).filter((o) => o.selected).map((o) => parseInt(o.value, 10)),
      ...choice,
    };
    const btn = qs("#co-submit", wrap);
    btn.disabled = true;
    btn.textContent = t("creating");
    try {
      const data = await api.post("/api/orders", payload);
      closeModal();
      toast(`${t("create_order")}: ${data.order.number}`, "success");
      if (onCreated) onCreated(data.order);
      navigate("#/order/" + data.order.id);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = t("create_btn");
      if (err.code === "merge_choice_required") {
        renderCandidates(err.data.candidates || []);
        errHost.textContent = t("merge_choice_required");
      } else {
        errHost.textContent = err.message || t("error");
      }
    }
  };
}
