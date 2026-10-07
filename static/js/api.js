import { t } from "./i18n.js";

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message || code || t("error"));
    this.status = status;
    this.code = code;
    this.data = data || {};
  }
}

async function request(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    });
  } catch (e) {
    throw new ApiError(0, "network", t("network_error"));
  }
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    const err = new ApiError(
      res.status,
      data && data.error,
      data && data.message,
      data
    );
    if (res.status === 401 && !url.includes("/api/auth/login")) {
      window.dispatchEvent(new CustomEvent("app:unauthorized"));
    }
    if (data && data.error === "password_required") {
      window.dispatchEvent(new CustomEvent("app:password-required"));
    }
    throw err;
  }
  return data;
}

export const get = (url) => request("GET", url);
export const post = (url, body) => request("POST", url, body === undefined ? {} : body);
export const put = (url, body) => request("PUT", url, body === undefined ? {} : body);
export const del = (url, body) => request("DELETE", url, body);

export function qs(params) {
  const parts = [];
  for (const [k, v] of Object.entries(params || {})) {
    if (v === "" || v === null || v === undefined || v === false) continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.length ? "?" + parts.join("&") : "";
}
