import secrets

from flask import Blueprint, jsonify, request, session

from .. import db, ratelimit
from ..security import audit, current_user, hash_password, login_required, verify_password
from ..services import notify, telegram
from ..timeutil import iso

bp = Blueprint("auth", __name__)

PUBLIC_SETTINGS = [
    "service_name",
    "default_lang",
    "due_soon_hours",
    "org_tz_offset",
]


def _user_payload(user: dict) -> dict:
    role = db.one("SELECT * FROM roles WHERE id=?", (user.get("role_id"),)) if user.get("role_id") else None
    perms = set()
    if role:
        perms = {
            r["perm_key"]
            for r in db.query(
                "SELECT perm_key FROM role_permissions WHERE role_id=?", (role["id"],)
            )
        }
    return {
        "id": user["id"],
        "login": user["login"],
        "full_name": user["full_name"] or user["login"],
        "lang": db.effective_lang(user),
        "role": {"id": role["id"], "key": role["key"], "name_ru": role["name_ru"], "name_en": role["name_en"]}
        if role
        else None,
        "permissions": sorted(perms),
        "must_change_password": bool(user.get("must_change_password")),
        "telegram": {
            "linked": bool(user.get("telegram_chat_id")),
            "chat_id": user.get("telegram_chat_id"),
        },
        "active": bool(user.get("active")),
    }


@bp.post("/api/auth/login")
def login():
    data = request.get_json(force=True, silent=True) or {}
    login_name = (data.get("login") or "").strip()
    password = data.get("password") or ""
    ip = request.remote_addr or "?"
    lk = f"login:{login_name.lower()}"
    ik = f"login_ip:{ip}"
    if ratelimit.blocked(lk, 10, 900) or ratelimit.blocked(ik, 50, 900):
        audit("login_throttled", "user", login_name, "rate limit", )
        return (
            jsonify(
                {
                    "error": "rate_limited",
                    "message": "Слишком много попыток входа. Повторите через несколько минут.",
                }
            ),
            429,
        )
    user = db.one("SELECT * FROM users WHERE lower(login)=lower(?)", (login_name,))
    if not user or not verify_password(user.get("password_hash"), password):
        ratelimit.hit(lk, 10, 900)
        ratelimit.hit(ik, 50, 900)
        audit("login_failed", "user", login_name, "invalid credentials")
        return jsonify({"error": "invalid_credentials", "message": "Неверный логин или пароль"}), 401
    ratelimit.reset(lk)
    if not user.get("active"):
        return jsonify({"error": "blocked", "message": "Учётная запись заблокирована"}), 403
    if not user.get("role_id"):
        return jsonify({"error": "no_role", "message": "Учётной записи не назначена роль"}), 403

    token = secrets.token_hex(32)
    db.execute(
        "INSERT INTO sessions(token, user_id, created_at, last_seen_at, ip, user_agent) "
        "VALUES(?,?,?,?,?,?)",
        (
            token,
            user["id"],
            iso(),
            iso(),
            request.remote_addr,
            (request.headers.get("User-Agent") or "")[:300],
        ),
    )
    db.execute(
        "UPDATE users SET last_login_at=?, failed_logins=0 WHERE id=?", (iso(), user["id"])
    )
    session.clear()
    session["token"] = token
    session.permanent = True
    audit("login", "user", user["id"], user["login"], user_id=user["id"])
    return jsonify({"user": _user_payload(user)})


@bp.post("/api/auth/logout")
def logout():
    token = session.get("token")
    if token:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        audit("logout", "user", current_user().get("id") if current_user() else None)
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/me")
def me():
    settings = db.get_settings()
    pub = {k: settings.get(k) for k in PUBLIC_SETTINGS}
    user = current_user()
    if not user:
        return jsonify({"user": None, "settings": pub})
    payload = _user_payload(user)
    payload["unread"] = notify.unread_count(user["id"])
    payload["settings"] = dict(pub)
    payload["settings"]["telegram"] = telegram.bot_info()
    return jsonify({"user": payload})


@bp.post("/api/auth/password")
def change_password_first():
    user = current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    new_password = data.get("new_password") or ""
    old_password = data.get("old_password") or ""
    if len(new_password) < 6:
        return jsonify({"error": "weak", "message": "Пароль должен быть не короче 6 символов"}), 400
    pk = f"pwd:{user['id']}"
    if ratelimit.blocked(pk, 10, 900):
        return (
            jsonify(
                {
                    "error": "rate_limited",
                    "message": "Слишком много попыток. Повторите через несколько минут.",
                }
            ),
            429,
        )
    if not verify_password(user.get("password_hash"), old_password):
        ratelimit.hit(pk, 10, 900)
        return jsonify({"error": "invalid_old", "message": "Текущий пароль неверен"}), 400
    ratelimit.reset(pk)
    db.execute(
        "UPDATE users SET password_hash=?, must_change_password=0, updated_at=? WHERE id=?",
        (hash_password(new_password), iso(), user["id"]),
    )
    cur_token = session.get("token")
    db.execute(
        "DELETE FROM sessions WHERE user_id=? AND token<>?",
        (user["id"], cur_token or ""),
    )
    audit("password_change", "user", user["id"], "", user_id=user["id"])
    return jsonify({"ok": True, "user": _user_payload(db.one("SELECT * FROM users WHERE id=?", (user["id"],)))})


@bp.post("/api/auth/recovery")
def recovery_request():
    data = request.get_json(force=True, silent=True) or {}
    login_name = (data.get("login") or "").strip()
    ip = request.remote_addr or "?"
    rk = f"rec_req:{login_name.lower()}"
    rip = f"rec_req_ip:{ip}"
    if ratelimit.blocked(rk, 3, 600) or ratelimit.blocked(rip, 10, 600):
        audit("recovery_throttled", "user", login_name, "rate limit")
        return (
            jsonify(
                {
                    "error": "rate_limited",
                    "message": "Слишком много запросов. Повторите позже.",
                }
            ),
            429,
        )
    ratelimit.hit(rk, 3, 600)
    ratelimit.hit(rip, 10, 600)
    user = db.one("SELECT * FROM users WHERE lower(login)=lower(?)", (login_name,))
    if not user or not user.get("telegram_chat_id"):
        return (
            jsonify(
                {
                    "error": "no_telegram",
                    "message": "Telegram не подключён. Обратитесь к администратору.",
                }
            ),
            404,
        )
    code = secrets.token_hex(3).upper()
    db.execute(
        "UPDATE users SET telegram_link_code=? WHERE id=?", (code, user["id"])
    )
    telegram.send(
        user["telegram_chat_id"],
        f"Код восстановления доступа: <b>{code}</b>\n"
        "Введите его в форме восстановления. Код действителен до использования.",
    )
    audit("recovery_request", "user", user["id"], "", user_id=user["id"])
    return jsonify({"ok": True, "sent": True})


@bp.post("/api/auth/recovery/confirm")
def recovery_confirm():
    data = request.get_json(force=True, silent=True) or {}
    login_name = (data.get("login") or "").strip()
    code = (data.get("code") or "").strip().upper()
    new_password = data.get("new_password") or ""
    ck = f"rec_cf:{login_name.lower()}"
    if ratelimit.blocked(ck, 10, 600):
        return (
            jsonify(
                {
                    "error": "rate_limited",
                    "message": "Слишком много попыток. Запросите новый код.",
                }
            ),
            429,
        )
    user = db.one("SELECT * FROM users WHERE lower(login)=lower(?)", (login_name,))
    if not user or not user.get("telegram_link_code") or user["telegram_link_code"] != code:
        ratelimit.hit(ck, 10, 600)
        if user and ratelimit.blocked(ck, 8, 600):
            db.execute(
                "UPDATE users SET telegram_link_code=NULL WHERE id=?", (user["id"],)
            )
        audit("recovery_failed", "user", user["id"] if user else "", "bad code")
        return jsonify({"error": "bad_code", "message": "Неверный код"}), 400
    ratelimit.reset(ck)
    if len(new_password) < 6:
        return jsonify({"error": "weak", "message": "Пароль должен быть не короче 6 символов"}), 400
    db.execute(
        "UPDATE users SET password_hash=?, telegram_link_code=NULL, "
        "must_change_password=0, active=1 WHERE id=?",
        (hash_password(new_password), user["id"]),
    )
    db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    audit("password_recovered", "user", user["id"], "", user_id=user["id"])
    return jsonify({"ok": True})


@bp.get("/api/profile")
@login_required
def profile():
    user = current_user()
    payload = _user_payload(user)
    payload["unread"] = notify.unread_count(user["id"])
    return jsonify({"user": payload})


@bp.put("/api/profile")
@login_required
def profile_update():
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    default = db.get_settings().get("default_lang")
    default = default if default in ("ru", "en") else "ru"
    lang = data.get("lang")
    if lang not in ("ru", "en"):
        lang = db.effective_lang(user)
    custom = 0 if lang == default else 1
    full_name = (data.get("full_name") or user.get("full_name") or "").strip()
    db.execute(
        "UPDATE users SET lang=?, lang_custom=?, full_name=?, updated_at=? WHERE id=?",
        (lang, custom, full_name, iso(), user["id"]),
    )
    audit("profile_update", "user", user["id"], lang, user_id=user["id"])
    return jsonify({"user": _user_payload(db.one("SELECT * FROM users WHERE id=?", (user["id"],)))})


@bp.post("/api/profile/telegram/code")
@login_required
def telegram_code():
    user = current_user()
    code = secrets.token_hex(3).upper()
    db.execute("UPDATE users SET telegram_link_code=? WHERE id=?", (code, user["id"]))
    link = telegram.start_link(code)
    info = telegram.bot_info()
    return jsonify({"code": code, "link": link, "bot": info})


@bp.delete("/api/profile/telegram")
@login_required
def telegram_unlink():
    user = current_user()
    db.execute(
        "UPDATE users SET telegram_chat_id=NULL, telegram_linked_at=NULL WHERE id=?",
        (user["id"],),
    )
    audit("telegram_unlink", "user", user["id"], "", user_id=user["id"])
    return jsonify({"ok": True})
