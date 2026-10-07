import { t, getLang } from "./i18n.js";

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function qs(sel, root) {
  return (root || document).querySelector(sel);
}

export function qsa(sel, root) {
  return Array.from((root || document).querySelectorAll(sel));
}

export function on(root, event, selector, handler) {
  root.addEventListener(event, (e) => {
    const target = e.target.closest(selector);
    if (target && root.contains(target)) handler(e, target);
  });
}

/* ------------------------------------------------------------- toasts */
export function toast(message, type = "") {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity .3s";
    setTimeout(() => el.remove(), 320);
  }, 3600);
}

/* ------------------------------------------------------------- modals */
let activeModal = null;

export function openModal({ title, body, footer = "", size = "", onClose }) {
  closeModal();
  const root = document.getElementById("modal-root");
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.innerHTML = `
    <div class="modal ${size ? "modal-" + size : ""}" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>${title}</h3>
        <button class="icon-btn" data-close aria-label="close">✕</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
    </div>`;
  root.appendChild(wrap);
  activeModal = { wrap, onClose };
  wrap.addEventListener("click", (e) => {
    if (e.target === wrap || e.target.closest("[data-close]")) {
      closeModal();
      if (onClose) onClose();
    }
  });
  const focusable = wrap.querySelector("input, select, textarea, .btn-primary");
  if (focusable) setTimeout(() => focusable.focus(), 40);
  return wrap;
}

export function closeModal() {
  if (activeModal) {
    activeModal.wrap.remove();
    const cb = activeModal.onClose;
    activeModal = null;
    if (cb) cb();
  }
}

export function modalOpen() {
  return !!activeModal;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && activeModal) {
    e.preventDefault();
    closeModal();
  }
});

export function confirmDialog(message, { title = "", danger = false, okLabel = "" } = {}) {
  return new Promise((resolve) => {
    const wrap = openModal({
      title: title || t("delete_confirm"),
      size: "sm",
      body: `<p style="margin:0;font-size:14px">${esc(message)}</p>`,
      footer: `
        <button class="btn" data-no>${esc(t("cancel"))}</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-yes>${esc(okLabel || t("save"))}</button>`,
      onClose: () => resolve(false),
    });
    wrap.querySelector("[data-no]").onclick = () => closeModal();
    wrap.querySelector("[data-yes]").onclick = () => {
      activeModal = null;
      wrap.remove();
      resolve(true);
    };
  });
}

/* ------------------------------------------------------------- format */
export function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d)) return value;
  const off = (window.APP_TZ || 180) * 60000;
  const local = new Date(d.getTime() + off + d.getTimezoneOffset() * 60000);
  return local.toLocaleDateString(getLang() === "en" ? "en-GB" : "ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d)) return value;
  const off = (window.APP_TZ || 180) * 60000;
  const local = new Date(d.getTime() + off + d.getTimezoneOffset() * 60000);
  return local.toLocaleString(getLang() === "en" ? "en-GB" : "ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtTime(value) {
  if (!value) return "—";
  return fmtDateTime(value).slice(-5);
}

export function fmtDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (getLang() === "en") {
    return h ? `${h}h ${m}m` : m ? `${m}m ${seconds % 60}s` : `${seconds}s`;
  }
  return h ? `${h}ч ${m}м` : m ? `${m}м ${seconds % 60}с` : `${seconds}s`;
}

export function isOverdue(order) {
  if (!order.due_at) return false;
  if (["issued", "cancelled"].includes(order.status_key || (order.status || {}).key)) return false;
  return new Date(order.due_at) < new Date();
}

export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export function debounce(fn, ms = 350) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function copyText(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => toast(t("copied"), "success"));
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    toast(t("copied"), "success");
  }
}
