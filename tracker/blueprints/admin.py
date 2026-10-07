import json

from flask import Blueprint, jsonify, request

from .. import db
from ..security import audit, current_user, hash_password, permission_required
from ..services import backup, notify, orders as oservice, telegram
from ..timeutil import iso

bp = Blueprint("admin", __name__)


def _err(message, code="error", status=400):
    return jsonify({"error": code, "message": message}), status


def _perm(check):
    return permission_required(check)


# ---------------------------------------------------------------- users
@bp.get("/api/admin/users")
@_perm("users.manage")
def users_list():
    rows = db.query(
        "SELECT u.id, u.login, u.full_name, u.lang, u.lang_custom, u.active, u.role_id, u.created_at, "
        "u.last_login_at, u.telegram_chat_id, u.must_change_password, r.key role_key, "
        "r.name_ru role_ru, r.name_en role_en FROM users u "
        "LEFT JOIN roles r ON r.id=u.role_id ORDER BY u.login"
    )
    return jsonify({"users": rows})


@bp.post("/api/admin/users")
@_perm("users.manage")
def user_create():
    data = request.get_json(force=True, silent=True) or {}
    login_name = (data.get("login") or "").strip()
    if not login_name:
        return _err("Логин обязателен", "login_required")
    if db.one("SELECT id FROM users WHERE lower(login)=lower(?)", (login_name,)):
        return _err("Логин уже существует", "exists", 409)
    role_id = data.get("role_id")
    if role_id and not db.one("SELECT id FROM roles WHERE id=?", (role_id,)):
        return _err("Роль не найдена", "role_not_found", 404)
    pwd = data.get("password") or "changeme"
    default = db.get_settings().get("default_lang")
    default = default if default in ("ru", "en") else "ru"
    lang = data.get("lang") or default
    if lang not in ("ru", "en"):
        lang = default
    db.execute(
        "INSERT INTO users(login, password_hash, must_change_password, role_id, full_name, "
        "lang, lang_custom, active, created_at) VALUES(?,?,?,?,?,?,?,1,?)",
        (
            login_name,
            hash_password(pwd),
            1,
            role_id,
            (data.get("full_name") or "").strip(),
            lang,
            0 if lang == default else 1,
            iso(),
        ),
    )
    audit("user_create", "user", login_name)
    return jsonify({"ok": True}), 201


@bp.put("/api/admin/users/<int:user_id>")
@_perm("users.manage")
def user_update(user_id):
    data = request.get_json(force=True, silent=True) or {}
    me = current_user()
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        return _err("Пользователь не найден", "not_found", 404)
    if "role_id" in data:
        rid = data.get("role_id")
        if rid and not db.one("SELECT id FROM roles WHERE id=?", (rid,)):
            return _err("Роль не найдена", "role_not_found", 404)
        db.execute("UPDATE users SET role_id=? WHERE id=?", (rid, user_id))
        audit("user_role", "user", user_id, f"{user.get('role_id')} -> {rid}")
        if not rid:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    if "active" in data:
        active = 1 if data.get("active") else 0
        if user_id == me["id"] and not active:
            return _err("Нельзя заблокировать собственную учётную запись", "self_block")
        db.execute("UPDATE users SET active=? WHERE id=?", (active, user_id))
        if not active:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit("user_block" if not active else "user_unblock", "user", user_id)
    if "full_name" in data:
        db.execute(
            "UPDATE users SET full_name=? WHERE id=?", (data.get("full_name") or "", user_id)
        )
    if "lang" in data and data.get("lang") in ("ru", "en"):
        default = db.get_settings().get("default_lang")
        default = default if default in ("ru", "en") else "ru"
        custom = 0 if data["lang"] == default else 1
        db.execute(
            "UPDATE users SET lang=?, lang_custom=? WHERE id=?",
            (data["lang"], custom, user_id),
        )
    if data.get("reset_password"):
        pwd = data.get("password") or "changeme"
        db.execute(
            "UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
            (hash_password(pwd), user_id),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit("user_password_reset", "user", user_id)
    db.execute("UPDATE users SET updated_at=? WHERE id=?", (iso(), user_id))
    return jsonify({"ok": True})


@bp.delete("/api/admin/users/<int:user_id>")
@_perm("users.manage")
def user_delete(user_id):
    me = current_user()
    if me["id"] == user_id:
        return _err("Нельзя удалить себя", "self")
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        return _err("Пользователь не найден", "not_found", 404)
    db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    db.execute(
        "UPDATE users SET role_id=NULL, active=0, updated_at=? WHERE id=?", (iso(), user_id)
    )
    audit("user_delete", "user", user_id, user["login"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------- roles
@bp.get("/api/admin/roles")
@_perm("roles.manage")
def roles_list():
    roles = db.query("SELECT * FROM roles ORDER BY id")
    for r in roles:
        r["permissions"] = [
            p["perm_key"]
            for p in db.query(
                "SELECT perm_key FROM role_permissions WHERE role_id=?", (r["id"],)
            )
        ]
    perms = db.query("SELECT * FROM permissions ORDER BY grp_ru, key")
    grouped = {}
    for p in perms:
        grouped.setdefault(p["grp_ru"], {"ru": p["grp_ru"], "en": p["grp_en"], "items": []})
        grouped[p["grp_ru"]]["items"].append(p)
    return jsonify({"roles": roles, "permission_groups": list(grouped.values())})


@bp.post("/api/admin/roles")
@_perm("roles.manage")
def role_create():
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get("key") or "").strip().lower()
    if not key:
        return _err("Ключ обязателен", "key_required")
    if db.one("SELECT id FROM roles WHERE key=?", (key,)):
        return _err("Роль уже существует", "exists", 409)
    rid = db.execute(
        "INSERT INTO roles(key, name_ru, name_en, is_system) VALUES(?,?,?,0)",
        (key, data.get("name_ru") or key, data.get("name_en") or key),
    )
    audit("role_create", "role", key)
    return jsonify({"id": rid}), 201


@bp.put("/api/admin/roles/<int:role_id>")
@_perm("roles.manage")
def role_update(role_id):
    data = request.get_json(force=True, silent=True) or {}
    role = db.one("SELECT * FROM roles WHERE id=?", (role_id,))
    if not role:
        return _err("Роль не найдена", "not_found", 404)
    db.execute(
        "UPDATE roles SET name_ru=?, name_en=? WHERE id=?",
        (
            data.get("name_ru") or role["name_ru"],
            data.get("name_en") or role["name_en"],
            role_id,
        ),
    )
    audit("role_update", "role", role_id)
    return jsonify({"ok": True})


@bp.delete("/api/admin/roles/<int:role_id>")
@_perm("roles.manage")
def role_delete(role_id):
    role = db.one("SELECT * FROM roles WHERE id=?", (role_id,))
    if not role:
        return _err("Роль не найдена", "not_found", 404)
    if role["is_system"]:
        return _err("Системную роль нельзя удалить", "system_role", 400)
    used = db.one("SELECT COUNT(*) c FROM users WHERE role_id=?", (role_id,))["c"]
    if used:
        return _err("Роль используется пользователями", "in_use", 409)
    db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    db.execute("DELETE FROM roles WHERE id=?", (role_id,))
    audit("role_delete", "role", role["key"])
    return jsonify({"ok": True})


@bp.put("/api/admin/roles/<int:role_id>/permissions")
@_perm("roles.manage")
def role_permissions(role_id):
    data = request.get_json(force=True, silent=True) or {}
    perms = data.get("permissions")
    if not isinstance(perms, list):
        return _err("Список прав не передан", "bad_request")
    valid = {p["key"] for p in db.query("SELECT key FROM permissions")}
    chosen = [p for p in perms if p in valid]
    con = db.connect()
    try:
        con.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
        for p in chosen:
            con.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id, perm_key) VALUES(?,?)",
                (role_id, p),
            )
        con.commit()
    finally:
        con.close()
    audit("role_permissions", "role", role_id, f"count={len(chosen)}")
    return jsonify({"ok": True, "count": len(chosen)})


# ---------------------------------------------------------------- statuses
@bp.get("/api/admin/statuses")
@_perm("board.manage")
def statuses_list():
    rows = db.query("SELECT * FROM statuses ORDER BY position, id")
    for r in rows:
        r["orders_count"] = db.one(
            "SELECT COUNT(*) c FROM orders WHERE status_id=? AND deleted=0", (r["id"],)
        )["c"]
    return jsonify({"statuses": rows})


@bp.post("/api/admin/statuses")
@_perm("board.manage")
def status_create():
    data = request.get_json(force=True, silent=True) or {}
    name_ru = (data.get("name_ru") or "").strip()
    if not name_ru:
        return _err("Название обязательно", "name_required")
    key = (data.get("key") or "").strip().lower() or f"custom_{int(iso()[:10].replace('-', ''))}"
    if db.one("SELECT id FROM statuses WHERE key=?", (key,)):
        return _err("Ключ уже существует", "exists", 409)
    pos = db.one("SELECT COALESCE(MAX(position),0)+1 p FROM statuses")["p"]
    sid = db.execute(
        "INSERT INTO statuses(key, name_ru, name_en, position, color, is_system, active) "
        "VALUES(?,?,?,?,?,0,1)",
        (
            key,
            name_ru,
            data.get("name_en") or name_ru,
            data.get("position") or pos,
            data.get("color") or "#64748b",
        ),
    )
    audit("status_create", "status", key)
    return jsonify({"id": sid}), 201


@bp.put("/api/admin/statuses/<int:status_id>")
@_perm("board.manage")
def status_update(status_id):
    data = request.get_json(force=True, silent=True) or {}
    st = db.one("SELECT * FROM statuses WHERE id=?", (status_id,))
    if not st:
        return _err("Статус не найден", "not_found", 404)
    db.execute(
        "UPDATE statuses SET name_ru=?, name_en=?, color=?, position=?, active=? WHERE id=?",
        (
            data.get("name_ru") or st["name_ru"],
            data.get("name_en") or st["name_en"],
            data.get("color") or st["color"],
            int(data.get("position", st["position"])),
            int(data.get("active", st["active"])),
            status_id,
        ),
    )
    audit("status_update", "status", status_id)
    return jsonify({"ok": True})


@bp.post("/api/admin/statuses/reorder")
@_perm("board.manage")
def status_reorder():
    data = request.get_json(force=True, silent=True) or {}
    order = data.get("order") or []
    con = db.connect()
    try:
        for i, sid in enumerate(order, start=1):
            con.execute("UPDATE statuses SET position=? WHERE id=?", (i, sid))
        con.commit()
    finally:
        con.close()
    audit("status_reorder", "status", ",".join(str(x) for x in order))
    return jsonify({"ok": True})


@bp.delete("/api/admin/statuses/<int:status_id>")
@_perm("board.manage")
def status_delete(status_id):
    st = db.one("SELECT * FROM statuses WHERE id=?", (status_id,))
    if not st:
        return _err("Статус не найден", "not_found", 404)
    count = db.one(
        "SELECT COUNT(*) c FROM orders WHERE status_id=? AND deleted=0", (status_id,)
    )["c"]
    if count:
        return _err("На статусе есть заказы — деактивируйте его", "in_use", 409)
    db.execute("DELETE FROM statuses WHERE id=?", (status_id,))
    audit("status_delete", "status", st["key"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------- work types
@bp.get("/api/admin/worktypes")
@_perm("worktypes.manage")
def worktypes_list():
    rows = db.query("SELECT * FROM work_types ORDER BY position, id")
    for r in rows:
        r["templates"] = db.query(
            "SELECT * FROM checklist_templates WHERE work_type_id=? ORDER BY position, id",
            (r["id"],),
        )
        r["orders_count"] = db.one(
            "SELECT COUNT(*) c FROM orders WHERE work_type_ids LIKE ? AND deleted=0",
            (f'%"{r["id"]}"%',),
        )["c"]
    return jsonify({"work_types": rows})


@bp.post("/api/admin/worktypes")
@_perm("worktypes.manage")
def worktype_create():
    data = request.get_json(force=True, silent=True) or {}
    name_ru = (data.get("name_ru") or "").strip()
    if not name_ru:
        return _err("Название обязательно", "name_required")
    pos = db.one("SELECT COALESCE(MAX(position),0)+1 p FROM work_types")["p"]
    wid = db.execute(
        "INSERT INTO work_types(name_ru, name_en, position, active) VALUES(?,?,?,1)",
        (name_ru, data.get("name_en") or name_ru, pos),
    )
    audit("worktype_create", "work_type", name_ru)
    return jsonify({"id": wid}), 201


@bp.put("/api/admin/worktypes/<int:wt_id>")
@_perm("worktypes.manage")
def worktype_update(wt_id):
    data = request.get_json(force=True, silent=True) or {}
    wt = db.one("SELECT * FROM work_types WHERE id=?", (wt_id,))
    if not wt:
        return _err("Тип не найден", "not_found", 404)
    db.execute(
        "UPDATE work_types SET name_ru=?, name_en=?, active=? WHERE id=?",
        (
            data.get("name_ru") or wt["name_ru"],
            data.get("name_en") or wt["name_en"],
            int(data.get("active", wt["active"])),
            wt_id,
        ),
    )
    audit("worktype_update", "work_type", wt_id)
    return jsonify({"ok": True})


@bp.delete("/api/admin/worktypes/<int:wt_id>")
@_perm("worktypes.manage")
def worktype_delete(wt_id):
    wt = db.one("SELECT * FROM work_types WHERE id=?", (wt_id,))
    if not wt:
        return _err("Тип не найден", "not_found", 404)
    con = db.connect()
    try:
        con.execute("DELETE FROM checklist_templates WHERE work_type_id=?", (wt_id,))
        con.execute("DELETE FROM work_types WHERE id=?", (wt_id,))
        con.commit()
    finally:
        con.close()
    audit("worktype_delete", "work_type", wt["name_ru"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------- checklist templates
@bp.get("/api/admin/checklist-templates")
@_perm("checklists.manage")
def checklist_templates():
    rows = db.query(
        "SELECT t.*, w.name_ru worktype_ru, w.name_en worktype_en FROM checklist_templates t "
        "JOIN work_types w ON w.id=t.work_type_id ORDER BY w.position, t.position, t.id"
    )
    return jsonify({"templates": rows, "work_types": db.query("SELECT * FROM work_types ORDER BY position")})


@bp.post("/api/admin/checklist-templates")
@_perm("checklists.manage")
def checklist_template_create():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text_ru") or "").strip()
    wt_id = data.get("work_type_id")
    if not text or not wt_id:
        return _err("Текст и тип работ обязательны", "bad_request")
    pos = db.one(
        "SELECT COALESCE(MAX(position),0)+1 p FROM checklist_templates WHERE work_type_id=?",
        (wt_id,),
    )["p"]
    tid = db.execute(
        "INSERT INTO checklist_templates(work_type_id, text_ru, text_en, stage_key, required, "
        "position) VALUES(?,?,?,?,?,?)",
        (
            wt_id,
            text,
            data.get("text_en") or text,
            data.get("stage_key") or "",
            1 if data.get("required", True) else 0,
            pos,
        ),
    )
    audit("checklist_template_create", "checklist_template", tid)
    return jsonify({"id": tid}), 201


@bp.put("/api/admin/checklist-templates/<int:tpl_id>")
@_perm("checklists.manage")
def checklist_template_update(tpl_id):
    data = request.get_json(force=True, silent=True) or {}
    t = db.one("SELECT * FROM checklist_templates WHERE id=?", (tpl_id,))
    if not t:
        return _err("Шаблон не найден", "not_found", 404)
    db.execute(
        "UPDATE checklist_templates SET text_ru=?, text_en=?, stage_key=?, required=?, "
        "position=? WHERE id=?",
        (
            data.get("text_ru") or t["text_ru"],
            data.get("text_en", t["text_en"]),
            data.get("stage_key", t["stage_key"]),
            1 if data.get("required", t["required"]) else 0,
            int(data.get("position", t["position"])),
            tpl_id,
        ),
    )
    audit("checklist_template_update", "checklist_template", tpl_id)
    return jsonify({"ok": True})


@bp.delete("/api/admin/checklist-templates/<int:tpl_id>")
@_perm("checklists.manage")
def checklist_template_delete(tpl_id):
    db.execute("DELETE FROM checklist_templates WHERE id=?", (tpl_id,))
    audit("checklist_template_delete", "checklist_template", tpl_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- card templates
@bp.get("/api/admin/card-templates")
@_perm("templates.manage")
def card_templates():
    return jsonify({"templates": db.query("SELECT * FROM card_templates ORDER BY position, id")})


@bp.post("/api/admin/card-templates")
@_perm("templates.manage")
def card_template_create():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return _err("Название обязательно", "name_required")
    pos = db.one("SELECT COALESCE(MAX(position),0)+1 p FROM card_templates")["p"]
    tid = db.execute(
        "INSERT INTO card_templates(name, problem, original_works, work_type_ids, make, model, "
        "year, priority, active, position) VALUES(?,?,?,?,?,?,?,?,1,?)",
        (
            name,
            data.get("problem") or "",
            json.dumps(data.get("original_works") or [], ensure_ascii=False),
            json.dumps(data.get("work_type_ids") or []),
            data.get("make") or "",
            data.get("model") or "",
            data.get("year"),
            data.get("priority") or "normal",
            pos,
        ),
    )
    audit("card_template_create", "card_template", name)
    return jsonify({"id": tid}), 201


@bp.put("/api/admin/card-templates/<int:tpl_id>")
@_perm("templates.manage")
def card_template_update(tpl_id):
    data = request.get_json(force=True, silent=True) or {}
    t = db.one("SELECT * FROM card_templates WHERE id=?", (tpl_id,))
    if not t:
        return _err("Шаблон не найден", "not_found", 404)
    db.execute(
        "UPDATE card_templates SET name=?, problem=?, original_works=?, work_type_ids=?, "
        "make=?, model=?, year=?, priority=?, active=? WHERE id=?",
        (
            data.get("name") or t["name"],
            data.get("problem", t["problem"]),
            json.dumps(data.get("original_works") or json.loads(t["original_works"] or "[]"), ensure_ascii=False),
            json.dumps(data.get("work_type_ids") or json.loads(t["work_type_ids"] or "[]")),
            data.get("make", t["make"]),
            data.get("model", t["model"]),
            data.get("year", t["year"]),
            data.get("priority", t["priority"]),
            int(data.get("active", t["active"])),
            tpl_id,
        ),
    )
    audit("card_template_update", "card_template", tpl_id)
    return jsonify({"ok": True})


@bp.delete("/api/admin/card-templates/<int:tpl_id>")
@_perm("templates.manage")
def card_template_delete(tpl_id):
    db.execute("DELETE FROM card_templates WHERE id=?", (tpl_id,))
    audit("card_template_delete", "card_template", tpl_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- settings
@bp.get("/api/admin/settings")
@_perm("settings.manage")
def settings_get():
    settings = db.get_settings()
    safe = dict(settings)
    safe["telegram_token_set"] = bool(settings.get("telegram_token"))
    if "telegram_token" in safe:
        safe["telegram_token"] = "•" * 8 if settings.get("telegram_token") else ""
    safe["notify_types"] = notify.EMPLOYEE_TYPES
    safe["client_types"] = notify.CLIENT_TYPES
    safe["roles"] = db.query("SELECT key, name_ru, name_en FROM roles ORDER BY id")
    safe["statuses"] = db.query("SELECT key, name_ru, name_en FROM statuses ORDER BY position")
    return jsonify({"settings": safe})


@bp.put("/api/admin/settings")
@_perm("settings.manage")
def settings_update():
    data = request.get_json(force=True, silent=True) or {}
    allowed = {
        "service_name", "default_lang", "org_tz_offset", "session_timeout_min",
        "due_soon_hours", "overdue_repeat_hours", "ready_conditions", "cancel_reasons",
        "auto_assign", "backup_keep_days", "backup_time", "notify_matrix",
        "telegram_bot_login",
    }
    changed = []
    for key in allowed:
        if key in data:
            db.set_setting(key, data[key])
            changed.append(key)
    if data.get("telegram_token") and data["telegram_token"] != "•" * 8:
        db.set_setting("telegram_token", data["telegram_token"])
        changed.append("telegram_token")
        telegram.bot_info()
    audit("settings_update", "settings", ",".join(changed))
    return jsonify({"ok": True, "changed": changed})


# ---------------------------------------------------------------- audit / archive
@bp.get("/api/admin/audit")
@_perm("audit.view")
def audit_list():
    limit = min(int(request.args.get("limit") or 200), 1000)
    where = "1=1"
    args = []
    if request.args.get("user_id"):
        where += " AND a.user_id=?"
        args.append(int(request.args["user_id"]))
    if request.args.get("action"):
        where += " AND a.action LIKE ?"
        args.append(f"%{request.args['action']}%")
    rows = db.query(
        f"SELECT a.*, u.login, u.full_name FROM audit_log a "
        f"LEFT JOIN users u ON u.id=a.user_id WHERE {where} "
        f"ORDER BY a.id DESC LIMIT ?",
        args + [limit],
    )
    return jsonify({"audit": rows, "users": db.query("SELECT id, login, full_name FROM users")})


@bp.get("/api/admin/orders")
@_perm("order.restore")
def admin_orders():
    view = request.args.get("view") or "deleted"
    if view == "deleted":
        rows = db.query(
            "SELECT o.*, s.name_ru status_ru, s.name_en status_en FROM orders o "
            "JOIN statuses s ON s.id=o.status_id WHERE o.deleted=1 "
            "ORDER BY o.deleted_at DESC"
        )
    else:
        rows = db.query(
            "SELECT o.*, s.name_ru status_ru, s.name_en status_en FROM orders o "
            "JOIN statuses s ON s.id=o.status_id WHERE o.archive=1 AND o.deleted=0 "
            "ORDER BY o.updated_at DESC"
        )
    return jsonify({"orders": rows, "view": view})


# ---------------------------------------------------------------- backups
@bp.get("/api/admin/backups")
@_perm("backup.manage")
def backups_list():
    return jsonify({"backups": backup.list_backups(), "settings": {
        "backup_keep_days": db.get_settings().get("backup_keep_days"),
        "backup_time": db.get_settings().get("backup_time"),
    }})


@bp.post("/api/admin/backups")
@_perm("backup.manage")
def backup_create():
    res = backup.create_backup("manual")
    return jsonify(res), 201


@bp.post("/api/admin/backups/<int:backup_id>/restore")
@_perm("backup.manage")
def backup_restore(backup_id):
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("confirm"):
        return _err("Требуется подтверждение восстановления", "confirm_required", 409)
    res = backup.restore_backup(backup_id, current_user())
    if not res.get("ok"):
        return _err("Ошибка восстановления", res.get("error", "error"), 404)
    return jsonify(res)


@bp.get("/api/admin/telegram")
@_perm("telegram.manage")
def telegram_info():
    return jsonify({"bot": telegram.bot_info(), "settings": {
        "telegram_bot_login": db.get_settings().get("telegram_bot_login", ""),
        "token_set": bool(db.get_settings().get("telegram_token")),
    }})
