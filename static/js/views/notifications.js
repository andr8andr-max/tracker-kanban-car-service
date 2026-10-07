import * as api from "../api.js";
import { t } from "../i18n.js";
import { esc, qs, qsa, toast, fmtDateTime } from "../ui.js";
import { state, navigate, icon } from "../app.js";

let filter = "all";

export async function renderNotifications(container) {
  container.innerHTML = `
    <div class="page">
      <div class="page-head">
        <h1>${esc(t("nav_notifications"))}</h1>
        <div class="spacer"></div>
        <button class="chip ${filter === "all" ? "active" : ""}" id="nf-all">${esc(t("all"))}</button>
        <button class="chip ${filter === "unread" ? "active" : ""}" id="nf-unread">${esc(t("unread"))}</button>
        <button class="btn btn-sm" id="nf-readall">${esc(t("read_all"))}</button>
      </div>
      <div class="panel" id="nf-list"><div class="hint">${esc(t("loading"))}</div></div>
    </div>`;

  qs("#nf-all").onclick = () => { filter = "all"; renderNotifications(container); };
  qs("#nf-unread").onclick = () => { filter = "unread"; renderNotifications(container); };
  qs("#nf-readall").onclick = async () => {
    try {
      const data = await api.post("/api/notifications/read", {});
      state.unread = data.unread;
      toast(t("saved"), "success");
      renderNotifications(container);
      updateBell();
    } catch (e) { toast(e.message, "error"); }
  };

  const data = await api.get("/api/notifications" + api.qs({ filter }));
  state.unread = data.unread;
  updateBell();

  const list = data.notifications;
  const host = qs("#nf-list");
  if (!list.length) {
    host.innerHTML = `<div class="hint" style="padding:24px;text-align:center">${esc(t("no_notifications"))}</div>`;
    return;
  }
  host.innerHTML = list.map((n) => `
    <div class="notif ${n.read ? "" : "unread"}" data-id="${n.id}" data-link="${esc(n.link || "")}">
      <div class="ntype">${icon(n.type === "system" ? "gear" : "bell")}</div>
      <div style="flex:1;min-width:0">
        <div class="ntitle">${esc(n.title || n.type_label)}</div>
        ${n.title && n.type_label ? `<div class="ntype-label hint">${esc(n.type_label)}</div>` : ""}
        ${n.body ? `<div class="nbody">${esc(n.body)}</div>` : ""}
        <div class="ntime">${esc(fmtDateTime(n.created_at))}</div>
      </div>
      ${n.read ? "" : `<span class="badge badge-blue">${esc(t("unread"))}</span>`}
    </div>`).join("");

  qsa(".notif", host).forEach((el) => (el.onclick = async () => {
    const id = parseInt(el.dataset.id, 10);
    const link = el.dataset.link;
    if (!el.classList.contains("unread")) {
      if (link) navigate(link);
      return;
    }
    try {
      const res = await api.post("/api/notifications/read", { ids: [id] });
      state.unread = res.unread;
      updateBell();
    } catch (e) {}
    if (link) navigate(link);
    else renderNotifications(container);
  }));
}

function updateBell() {
  const bell = document.getElementById("bell-count");
  const nav = document.getElementById("nav-count");
  const count = state.unread || 0;
  if (bell) {
    bell.style.display = count ? "flex" : "none";
    bell.textContent = count > 99 ? "99+" : count;
  }
  if (nav) {
    nav.style.display = count ? "inline-block" : "none";
    nav.textContent = count;
  }
}
