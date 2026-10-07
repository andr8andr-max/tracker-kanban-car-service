import threading

import requests

from .. import db
from ..timeutil import iso, now

API = "https://api.telegram.org/bot{token}/{method}"

_offset_lock = threading.Lock()


def bot_token() -> str:
    return (db.get_settings().get("telegram_token") or "").strip()


def is_configured() -> bool:
    return bool(bot_token())


def _call(method: str, payload: dict, timeout: int = 10) -> dict | None:
    token = bot_token()
    if not token:
        return None
    try:
        r = requests.post(
            API.format(token=token, method=method), json=payload, timeout=timeout
        )
        if r.status_code == 200:
            return r.json()
        return {"ok": False, "error": r.text[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def send(chat_id: str, text: str) -> bool:
    if not chat_id or not is_configured():
        return False
    res = _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    return bool(res and res.get("ok"))


def send_async(chat_id: str, text: str):
    if not chat_id:
        return
    threading.Thread(target=send, args=(chat_id, text), daemon=True).start()


def bot_info() -> dict:
    if not is_configured():
        return {"configured": False}
    res = _call("getMe", {})
    if res and res.get("ok"):
        u = res.get("result", {})
        return {
            "configured": True,
            "login": u.get("username"),
            "name": u.get("first_name"),
        }
    return {"configured": True, "error": (res or {}).get("error", "unknown")}


def start_link(code: str) -> str | None:
    login = (db.get_settings().get("telegram_bot_login") or "").strip()
    if not login:
        info = bot_info()
        login = info.get("login") or ""
    if not login:
        return None
    return f"https://t.me/{login}?start={code}"


def _handle_code(code: str, chat_id: str) -> bool:
    code = (code or "").strip().upper()
    if not code:
        return False
    user = db.one(
        "SELECT id FROM users WHERE telegram_link_code=?", (code,)
    )
    if user:
        db.execute(
            "UPDATE users SET telegram_chat_id=?, telegram_linked_at=?, "
            "telegram_link_code=NULL WHERE id=?",
            (str(chat_id), iso(), user["id"]),
        )
        send(str(chat_id), "✅ Telegram подключён к системе учёта.")
        return True
    binding = db.one(
        "SELECT id, order_id FROM client_bindings WHERE code=? AND bound_at IS NULL",
        (code,),
    )
    if binding:
        db.execute(
            "UPDATE client_bindings SET telegram_chat_id=?, bound_at=? WHERE id=?",
            (str(chat_id), iso(), binding["id"]),
        )
        send(
            str(chat_id),
            "✅ Telegram подключён. Вы будете получать уведомления о статусе заказа.",
        )
        return True
    return False


def poll_updates(limit: int = 30):
    if not is_configured():
        return
    with _offset_lock:
        offset = db.get_settings().get("telegram_offset", 0) or 0
        res = _call("getUpdates", {"offset": offset, "timeout": 0, "limit": limit})
        if not res or not res.get("ok"):
            return
        updates = res.get("result") or []
        max_id = offset
        for upd in updates:
            max_id = max(max_id, upd.get("update_id", 0))
            msg = upd.get("message") or upd.get("my_chat_message") or {}
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            text = (msg.get("text") or "").strip()
            if not chat_id or not text:
                continue
            parts = text.split()
            if len(parts) >= 2 and parts[0].lower() in ("/start", "start"):
                _handle_code(parts[1], chat_id)
            else:
                _handle_code(text, chat_id)
        if max_id:
            from ..db import set_setting

            set_setting("telegram_offset", max_id)
