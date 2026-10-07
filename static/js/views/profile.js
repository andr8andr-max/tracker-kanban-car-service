import * as api from "../api.js";
import { t, setLang, getLang, nameOf } from "../i18n.js";
import { esc, qs, qsa, toast, openModal, closeModal, confirmDialog, copyText } from "../ui.js";
import { state, boot, can } from "../app.js";

export async function renderProfile(container) {
  const data = await api.get("/api/profile");
  const u = data.user;
  state.user = u;

  container.innerHTML = `
    <div class="page">
      <div class="page-head"><h1>${esc(t("profile_title"))}</h1></div>
      <div class="grid-2">
        <div class="panel">
          <h3>${esc(t("profile_title"))}</h3>
          <dl class="kv">
            <dt>${esc(t("login"))}</dt><dd><b>${esc(u.login)}</b></dd>
            <dt>${esc(t("role"))}</dt><dd>${esc(u.role ? nameOf(u.role) : "—")}</dd>
          </dl>
          <div class="field">
            <label>${esc(t("full_name"))}</label>
            <input class="input" id="pf-name" value="${esc(u.full_name || "")}">
          </div>
          <div class="field">
            <label>${esc(t("language"))}</label>
            <select class="select" id="pf-lang">
              <option value="ru" ${u.lang === "ru" ? "selected" : ""}>Русский</option>
              <option value="en" ${u.lang === "en" ? "selected" : ""}>English</option>
            </select>
          </div>
          <button class="btn btn-primary" id="pf-save">${esc(t("save_profile"))}</button>
        </div>

        <div class="panel">
          <h3>${esc(t("change_password"))}</h3>
          <div class="hint" style="margin-bottom:12px">${esc(t("password_min"))}</div>
          <button class="btn" id="pf-pwd">${esc(t("change_password"))}</button>

          <h3 style="margin-top:22px">Telegram</h3>
          <div style="margin-bottom:10px">
            ${u.telegram && u.telegram.linked
              ? `<span class="badge badge-green">✓ ${esc(t("tg_linked"))}</span>
                 <button class="btn btn-sm" id="pf-tg-unlink" style="margin-left:8px">${esc(t("tg_unlink"))}</button>`
              : `<span class="badge badge-amber">${esc(t("tg_not_linked"))}</span>`}
          </div>
          ${u.telegram && u.telegram.linked ? "" : `<button class="btn" id="pf-tg">${esc(t("tg_connect"))}</button>`}
        </div>
      </div>
    </div>`;

  qs("#pf-save").onclick = async () => {
    try {
      const lang = qs("#pf-lang").value;
      const res = await api.put("/api/profile", {
        full_name: qs("#pf-name").value,
        lang,
      });
      state.user = res.user;
      setLang(lang);
      toast(t("saved"), "success");
      await boot();
    } catch (e) { toast(e.message, "error"); }
  };

  qs("#pf-pwd").onclick = () => passwordModal();

  const tg = qs("#pf-tg");
  if (tg) tg.onclick = () => telegramModal();

  const un = qs("#pf-tg-unlink");
  if (un) un.onclick = async () => {
    if (!(await confirmDialog(t("tg_unlink") + "?", { danger: true }))) return;
    await api.del("/api/profile/telegram");
    toast(t("saved"), "success");
    await boot();
    renderProfile(container);
  };
}

function passwordModal() {
  const wrap = openModal({
    title: t("change_password"),
    size: "sm",
    body: `
      <div class="field"><label>${esc(t("old_password"))}</label>
        <input class="input" id="pw-old" type="password" autocomplete="current-password"></div>
      <div class="field"><label>${esc(t("new_password"))}</label>
        <input class="input" id="pw-new" type="password" autocomplete="new-password"></div>
      <div class="error-text" id="pw-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("cancel"))}</button>
             <button class="btn btn-primary" id="pw-save">${esc(t("save"))}</button>`,
  });
  qs("#pw-save", wrap).onclick = async () => {
    const err = qs("#pw-err", wrap);
    err.textContent = "";
    const pass = qs("#pw-new", wrap).value;
    if (pass.length < 6) { err.textContent = t("password_min"); return; }
    try {
      const res = await api.post("/api/auth/password", {
        old_password: qs("#pw-old", wrap).value,
        new_password: pass,
      });
      state.user = res.user;
      closeModal();
      toast(t("password_changed"), "success");
    } catch (e) { err.textContent = e.message || t("error"); }
  };
}

function telegramModal() {
  const wrap = openModal({
    title: t("tg_connect"),
    size: "sm",
    body: `<div class="hint">${esc(t("tg_instruction"))}</div>
      <div class="field" style="margin-top:10px">
        <input class="input" id="tg-code" readonly value="…">
      </div>
      <div class="field">
        <input class="input" id="tg-link" readonly value="—">
      </div>
      <div class="error-text" id="tg-err"></div>`,
    footer: `<button class="btn" data-close>${esc(t("close"))}</button>
             <button class="btn btn-primary" id="tg-copy">${esc(t("tg_link_copy"))}</button>`,
  });
  api.post("/api/profile/telegram/code").then((d) => {
    qs("#tg-code", wrap).value = d.code;
    qs("#tg-link", wrap).value = d.link || t("tg_no_bot");
    if (!d.link) qs("#tg-err", wrap).textContent = t("tg_no_bot");
    qs("#tg-copy", wrap).onclick = () => copyText(d.link || d.code);
  }).catch((e) => { qs("#tg-err", wrap).textContent = e.message; });
}
