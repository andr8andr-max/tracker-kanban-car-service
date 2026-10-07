import * as api from "./api.js";
import { t, setLang, getLang, nameOf } from "./i18n.js";
import { esc, qs, qsa, toast, openModal, closeModal, initials } from "./ui.js";
import { renderBoard } from "./views/board.js";
import { renderOrder } from "./views/order.js";
import { renderNotifications } from "./views/notifications.js";
import { renderStats } from "./views/stats.js";
import { renderProfile } from "./views/profile.js";
import { renderAdmin } from "./views/admin.js";

export const state = { user: null, meta: null, unread: 0 };

export function can(key) {
  return !!(state.user && state.user.permissions && state.user.permissions.includes(key));
}

export function langOf(obj) {
  return nameOf(obj);
}

export function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

export async function loadMeta() {
  state.meta = await api.get("/api/meta");
  return state.meta;
}

const app = () => document.getElementById("app");

function applyPubLang(pub) {
  if (pub && pub.service_name) state.serviceName = pub.service_name;
  if (pub && pub.default_lang && !localStorage.getItem("tracker_lang")) setLang(pub.default_lang);
}

/* ================================================================= auth */
export function renderLogin(message = "") {
  const pref = localStorage.getItem("tracker_lang");
  if (pref) setLang(pref);
  const html = `
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <!-- LOGO: заменить на логотип компании -->
        <div class="logo">AS</div>
        <div>
          <div class="login-title">${esc(t("app_name"))}</div>
          <div class="login-sub">${esc(state.serviceName || "")}</div>
        </div>
      </div>
      <form id="login-form">
        <div class="field">
          <label>${esc(t("login"))}</label>
          <input class="input" name="login" autocomplete="username" required autofocus>
        </div>
        <div class="field">
          <label>${esc(t("password"))}</label>
          <input class="input" name="password" type="password" autocomplete="current-password" required>
        </div>
        ${message ? `<div class="error-text" style="margin-bottom:10px">${esc(message)}</div>` : ""}
        <button class="btn btn-primary btn-block" type="submit">${esc(t("sign_in"))}</button>
      </form>
      <div class="login-links">
        <a href="#" id="lnk-forgot">${esc(t("forgot"))}</a>
        <span class="lang-toggle">
          <button type="button" data-lang="ru" class="${getLang() === "ru" ? "active" : ""}">RU</button>
          <button type="button" data-lang="en" class="${getLang() === "en" ? "active" : ""}">EN</button>
        </span>
      </div>
    </div>
  </div>`;
  app().innerHTML = html;

  qsa("[data-lang]", app()).forEach((b) => {
    b.onclick = () => {
      setLang(b.dataset.lang);
      localStorage.setItem("tracker_lang", b.dataset.lang);
      renderLogin();
    };
  });
  qs("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const data = await api.post("/api/auth/login", {
        login: fd.get("login"),
        password: fd.get("password"),
      });
      const pref = localStorage.getItem("tracker_lang");
      if (pref) {
        localStorage.removeItem("tracker_lang");
        if (pref !== data.user.lang) {
          data.user.lang = pref;
          try { await api.put("/api/profile", { lang: pref }); } catch (err2) { /* язык применится локально */ }
        }
      }
      state.user = data.user;
      setLang(state.user.lang);
      await boot();
    } catch (err) {
      toast(err.message || t("invalid_credentials"), "error");
    }
  };
  qs("#lnk-forgot").onclick = (e) => {
    e.preventDefault();
    recoveryModal();
  };
}

function recoveryModal() {
  const wrap = openModal({
    title: t("recovery_title"),
    body: `
      <div class="field">
        <label>${esc(t("login"))}</label>
        <input class="input" id="rec-login">
      </div>
      <div id="rec-step2" style="display:none">
        <div class="field">
          <label>${esc(t("recovery_code"))}</label>
          <input class="input" id="rec-code" autocomplete="one-time-code">
        </div>
        <div class="field">
          <label>${esc(t("new_password"))}</label>
          <input class="input" id="rec-pass" type="password" autocomplete="new-password">
        </div>
      </div>
      <div class="error-text" id="rec-err"></div>`,
      footer: `
        <button class="btn" data-close>${esc(t("cancel"))}</button>
        <button class="btn btn-primary" id="rec-go">${esc(t("recovery_send"))}</button>`,
  });
  let step = 1;
  qs("#rec-go", wrap).onclick = async () => {
    const err = qs("#rec-err", wrap);
    err.textContent = "";
    try {
      if (step === 1) {
        await api.post("/api/auth/recovery", { login: qs("#rec-login", wrap).value });
        qs("#rec-step2", wrap).style.display = "block";
        qs("#rec-go", wrap).textContent = t("recovery_confirm");
        step = 2;
      } else {
        await api.post("/api/auth/recovery/confirm", {
          login: qs("#rec-login", wrap).value,
          code: qs("#rec-code", wrap).value,
          new_password: qs("#rec-pass", wrap).value,
        });
        closeModal();
        toast(t("password_changed"), "success");
      }
    } catch (e) {
      err.textContent = e.message || t("error");
    }
  };
}

export function renderPasswordChange(message = "") {
  app().innerHTML = `
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="logo">AS</div>
        <div>
          <div class="login-title">${esc(t("first_login_title"))}</div>
          <div class="login-sub">${esc(t("first_login_sub"))}</div>
        </div>
      </div>
      <form id="pwd-form">
        <div class="field">
          <label>${esc(t("old_password"))}</label>
          <input class="input" name="old_password" type="password" autocomplete="current-password" required>
        </div>
        <div class="field">
          <label>${esc(t("new_password"))}</label>
          <input class="input" name="new_password" type="password" autocomplete="new-password" required>
        </div>
        ${message ? `<div class="error-text" style="margin-bottom:10px">${esc(message)}</div>` : ""}
        <button class="btn btn-primary btn-block" type="submit">${esc(t("save"))}</button>
      </form>
      <div class="login-links">
        <a href="#" id="pwd-logout">${esc(t("nav_logout"))}</a>
      </div>
    </div>
  </div>`;
  qs("#pwd-logout").onclick = async (e) => {
    e.preventDefault();
    await api.post("/api/auth/logout");
    const pub = state.user && state.user.settings;
    state.user = null;
    applyPubLang(pub);
    renderLogin();
  };
  qs("#pwd-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const data = await api.post("/api/auth/password", {
        old_password: fd.get("old_password"),
        new_password: fd.get("new_password"),
      });
      state.user = data.user;
      setLang(state.user.lang);
      toast(t("password_changed"), "success");
      await boot();
    } catch (err) {
      toast(err.message || t("error"), "error");
    }
  };
}

/* =============================================================== shell */
let shellLang = null;

function adminVisible() {
  return ["users.manage", "roles.manage", "board.manage", "worktypes.manage",
    "templates.manage", "checklists.manage", "settings.manage", "telegram.manage",
    "backup.manage", "audit.view"].some(can);
}

function renderShell() {
  const u = state.user;
  app().innerHTML = `
  <div class="shell">
    <header class="topbar">
      <button class="icon-btn menu-toggle" id="menu-toggle" aria-label="menu">☰</button>
      <div class="brand">
        <!-- LOGO: заменить на логотип компании -->
        <div class="logo">AS</div>
        <span class="brand-name">${esc(state.meta.service_name || t("app_name"))}</span>
      </div>
      <div class="top-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="global-search" placeholder="${esc(t("search_placeholder"))}">
      </div>
      <div class="topbar-spacer"></div>
      <button class="icon-btn" id="btn-bell" title="${esc(t("notifications"))}">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>
        <span class="badge-count" id="bell-count" style="display:none">0</span>
      </button>
      <div class="dropdown" id="user-dropdown">
        <div class="userchip" id="userchip">
          <div class="avatar">${esc(initials(u.full_name))}</div>
          <div>
            <div class="uname">${esc(u.full_name)}</div>
            <div class="urole">${esc(u.role ? langOf(u.role) : "")}</div>
          </div>
        </div>
      </div>
    </header>
    <div class="body">
      <aside class="sidebar" id="sidebar">
        <button class="nav-item" data-route="#/">${icon("board")} ${esc(t("nav_board"))}</button>
        <button class="nav-item" data-route="#/stats">${icon("chart")} ${esc(t("nav_stats"))}</button>
        <button class="nav-item" data-route="#/notifications">${icon("bell")} ${esc(t("nav_notifications"))}
          <span class="n-count" id="nav-count" style="display:none">0</span></button>
        <button class="nav-item" data-route="#/profile">${icon("user")} ${esc(t("nav_profile"))}</button>
        ${adminVisible() ? `<div class="nav-sep"></div>
        <div class="nav-label">${esc(t("nav_admin"))}</div>
        <button class="nav-item" data-route="#/admin">${icon("gear")} ${esc(t("nav_admin"))}</button>` : ""}
        <div style="flex:1"></div>
        <button class="nav-item" id="btn-logout">${icon("exit")} ${esc(t("nav_logout"))}</button>
      </aside>
      <main class="main"><div id="view"></div></main>
    </div>
  </div>`;

  qsa("[data-route]", app()).forEach((b) => (b.onclick = () => navigate(b.dataset.route)));
  qs("#btn-logout").onclick = async () => {
    await api.post("/api/auth/logout");
    const pub = state.user && state.user.settings;
    state.user = null;
    applyPubLang(pub);
    renderLogin();
  };
  qs("#menu-toggle").onclick = () => qs("#sidebar").classList.toggle("open");
  qs("#btn-bell").onclick = () => navigate("#/notifications");
  qs("#userchip").onclick = (e) => {
    e.stopPropagation();
    userMenu();
  };
  qs("#global-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      sessionStorage.setItem("board_q", e.target.value);
      navigate("#/");
      if (location.hash === "#/" || location.hash === "") route();
    }
  });
  document.addEventListener("click", closeMenus);
  updateBadge();
}

function closeMenus() {
  qsa(".dropdown-menu").forEach((m) => m.remove());
}

function userMenu() {
  closeMenus();
  const host = qs("#user-dropdown");
  const menu = document.createElement("div");
  menu.className = "dropdown-menu";
  menu.innerHTML = `
    <a href="#/profile">${icon("user")} ${esc(t("nav_profile"))}</a>
    <a href="#/notifications">${icon("bell")} ${esc(t("nav_notifications"))}</a>
    <div class="sep"></div>
    <span style="display:flex;gap:6px;padding:6px 10px">
      <button data-lang="ru" class="btn btn-sm ${getLang() === "ru" ? "btn-primary" : ""}">RU</button>
      <button data-lang="en" class="btn btn-sm ${getLang() === "en" ? "btn-primary" : ""}">EN</button>
    </span>
    <div class="sep"></div>
    <button class="danger" id="mm-logout">${icon("exit")} ${esc(t("nav_logout"))}</button>`;
  host.appendChild(menu);
  qsa("[data-lang]", menu).forEach((b) => (b.onclick = async () => {
    setLang(b.dataset.lang);
    try { await api.put("/api/profile", { lang: b.dataset.lang }); } catch (e) {}
    state.user.lang = b.dataset.lang;
    closeMenus();
    await boot();
  }));
  qs("#mm-logout", menu).onclick = async () => {
    await api.post("/api/auth/logout");
    const pub = state.user && state.user.settings;
    state.user = null;
    applyPubLang(pub);
    renderLogin();
  };
}

function icon(name) {
  const paths = {
    board: '<rect x="3" y="3" width="7" height="18" rx="1.5"/><rect x="14" y="3" width="7" height="11" rx="1.5"/>',
    chart: '<path d="M3 21h18"/><rect x="5" y="11" width="4" height="7"/><rect x="12" y="6" width="4" height="12"/><rect x="19" y="14" width="2" height="4"/>',
    bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a7.6 7.6 0 0 0 .1-6l-2-1.2-1.6 1.6-1.9-.6L13 5h-2l-1 3.2-1.9.6L6.5 7.2 4.5 8.4a7.6 7.6 0 0 0 .1 6L3 15.6v2.8l2.6.8 1.4 2.4 1.9-.6L10 23h2l1-3.4 1.9-.6 1.4 2.4 2.6-.8v-2.8z"/>',
    exit: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  };
  return `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
}
export { icon };

function updateBadge() {
  const count = state.unread || 0;
  const bell = qs("#bell-count");
  const nav = qs("#nav-count");
  if (bell) {
    bell.style.display = count ? "flex" : "none";
    bell.textContent = count > 99 ? "99+" : count;
  }
  if (nav) {
    nav.style.display = count ? "inline-block" : "none";
    nav.textContent = count;
  }
}

async function pollUnread() {
  if (!state.user) return;
  try {
    const data = await api.get("/api/notifications/unread-count");
    state.unread = data.unread;
    updateBadge();
  } catch (e) {}
}

/* ============================================================== router */
const routes = [
  { pattern: /^#\/order\/(\d+)$/, view: renderOrder },
  { pattern: /^#\/notifications$/, view: renderNotifications },
  { pattern: /^#\/stats$/, view: renderStats },
  { pattern: /^#\/profile$/, view: renderProfile },
  { pattern: /^#\/admin(?:\/(\w+))?$/, view: renderAdmin },
  { pattern: /^#\/?$/, view: renderBoard },
];

export async function route() {
  if (!state.user || state.user.must_change_password) return;
  const view = qs("#view");
  if (!view) return;
  const hash = location.hash || "#/";
  let matched = false;
  for (const r of routes) {
    const m = hash.match(r.pattern);
    if (m) {
      matched = true;
      closeMenus();
      try {
        await r.view(view, m.slice(1), { state, can, navigate, loadMeta, icon });
      } catch (err) {
        console.error(err);
        view.innerHTML = `<div class="page"><div class="alert alert-danger">${esc(err.message || t("error"))}</div></div>`;
      }
      highlightNav(hash);
      break;
    }
  }
  if (!matched) navigate("#/");
}

function highlightNav(hash) {
  qsa(".nav-item[data-route]").forEach((b) => {
    const r = b.dataset.route;
    const active = r === "#/" ? (hash === "#/" || hash === "") : hash.startsWith(r);
    b.classList.toggle("active", active);
  });
  const sidebar = qs("#sidebar");
  if (sidebar) sidebar.classList.remove("open");
}

/* =============================================================== boot */
export async function boot() {
  let pub = null;
  try {
    const data = await api.get("/api/me");
    state.user = data.user;
    pub = data.settings || null;
  } catch (e) {
    state.user = null;
  }
  if (!state.user) {
    applyPubLang(pub);
    renderLogin();
    return;
  }
  setLang(state.user.lang);
  if (state.user.must_change_password) {
    renderPasswordChange();
    return;
  }
  state.unread = state.user.unread || 0;
  window.APP_TZ = (state.user.settings && state.user.settings.org_tz_offset) || 180;
  if (!state.meta) {
    try { await loadMeta(); } catch (e) { console.error(e); }
  }
  if (!qs(".shell") || shellLang !== getLang()) {
    renderShell();
    shellLang = getLang();
  }
  updateBadge();
  await route();
}

window.addEventListener("app:unauthorized", () => {
  state.user = null;
  renderLogin();
});
window.addEventListener("app:password-required", () => {
  if (state.user) renderPasswordChange();
});
window.addEventListener("hashchange", () => route());

boot().then(() => {
  setInterval(pollUnread, 30000);
});
