from flask import Blueprint, jsonify, request

from .. import db
from ..security import login_required, user_perms
from ..services import checklist, notify, orders as oservice
from ..timeutil import norm_plate, norm_text, norm_vin, now, parse

bp = Blueprint("board", __name__)


def serialize_card(row: dict, users: dict) -> dict:
    progress = checklist.progress(row["id"])
    due = parse(row.get("due_at")) if row.get("due_at") else None
    overdue = bool(
        due
        and due < now()
        and row.get("status_key") not in ("issued", "cancelled")
        and not row.get("deleted")
    )
    return {
        "id": row["id"],
        "number": row["number"],
        "status_id": row["status_id"],
        "status_key": row["status_key"],
        "position": row["position"],
        "plate": row["plate"],
        "vin": row.get("vin") or "",
        "make": row.get("make") or "",
        "model": row.get("model") or "",
        "client_name": row.get("client_name") or "",
        "client_phone": row.get("client_phone") or "",
        "responsible_id": row.get("responsible_id"),
        "responsible_name": users.get(str(row.get("responsible_id")), row.get("responsible_name") or ""),
        "priority": row.get("priority") or "normal",
        "due_at": row.get("due_at"),
        "overdue": overdue,
        "parts_attention": bool(row.get("parts_attention")),
        "parts_expected_at": row.get("parts_expected_at"),
        "archive": bool(row.get("archive")),
        "work_type_ids": __import__("json").loads(row.get("work_type_ids") or "[]"),
        "checklist": progress,
        "created_at": row.get("created_at"),
        "approval_state": row.get("approval_state"),
        "has_vin": bool((row.get("vin") or "").strip()),
    }


def apply_filters(sql: str, args: list, f: dict) -> tuple[str, list]:
    where = []
    if f.get("mine"):
        where.append("(o.responsible_id=? OR o.id IN (SELECT order_id FROM order_stage_executors WHERE user_id=?))")
        args += [f["user_id"], f["user_id"]]
    if f.get("responsible"):
        if f["responsible"] == "none":
            where.append("o.responsible_id IS NULL")
        else:
            where.append("o.responsible_id=?")
            args.append(int(f["responsible"]))
    if f.get("priority"):
        where.append("o.priority=?")
        args.append(f["priority"])
    if f.get("overdue"):
        where.append("o.due_at IS NOT NULL AND o.due_at<? AND s.key NOT IN ('issued','cancelled')")
        args.append(now().isoformat())
    if f.get("due_from"):
        where.append("o.due_at>=?")
        args.append(f["due_from"])
    if f.get("due_to"):
        where.append("o.due_at<=?")
        args.append(f["due_to"])
    if f.get("created_from"):
        where.append("o.created_at>=?")
        args.append(f["created_from"])
    if f.get("created_to"):
        where.append("o.created_at<=?")
        args.append(f["created_to"])
    if f.get("work_type"):
        try:
            wid = int(f["work_type"])
        except (TypeError, ValueError):
            wid = None
        if wid is not None:
            where.append("EXISTS (SELECT 1 FROM json_each(o.work_type_ids) je WHERE je.value=?)")
            args.append(wid)
    if f.get("status_key"):
        where.append("s.key=?")
        args.append(f["status_key"])
    if f.get("q"):
        q = str(f["q"]).strip()
        nq = norm_plate(q)
        nv = norm_vin(q)
        like = f"%{q}%"
        where.append(
            "(o.plate LIKE ? OR o.vin LIKE ? OR o.client_name LIKE ? OR o.client_phone LIKE ? "
            "OR o.number LIKE ? OR o.plate_norm LIKE ? OR o.vin LIKE ?)"
        )
        args += [like, like, like, like, like, nq + "%", nv + "%"]
    if where:
        sql += " AND " + " AND ".join(where)
    return sql, args


@bp.get("/api/board")
@login_required
def board():
    from ..security import current_user

    user = current_user()
    f = {
        "mine": request.args.get("mine") in ("1", "true", "yes"),
        "responsible": request.args.get("responsible") or "",
        "priority": request.args.get("priority") or "",
        "overdue": request.args.get("overdue") in ("1", "true"),
        "due_from": request.args.get("due_from") or "",
        "due_to": request.args.get("due_to") or "",
        "created_from": request.args.get("created_from") or "",
        "created_to": request.args.get("created_to") or "",
        "work_type": request.args.get("work_type") or "",
        "status_key": request.args.get("status_key") or "",
        "q": request.args.get("q") or "",
        "user_id": user["id"],
    }
    include_archive = request.args.get("archive") in ("1", "true")
    lang = db.effective_lang(user)

    sql = (
        "SELECT o.*, s.key status_key, s.name_ru status_ru, s.name_en status_en, "
        "u.full_name responsible_name FROM orders o "
        "JOIN statuses s ON s.id=o.status_id "
        "LEFT JOIN users u ON u.id=o.responsible_id "
        "WHERE o.deleted=0"
    )
    args: list = []
    if not include_archive:
        sql += " AND o.archive=0"
    sql, args = apply_filters(sql, args, f)
    sql += " ORDER BY o.position, o.id"
    rows = db.query(sql, args)

    users = {
        str(u["id"]): (u["full_name"] or u["login"])
        for u in db.query("SELECT id, full_name, login FROM users")
    }
    statuses = oservice.statuses()
    cards = [serialize_card(r, users) for r in rows]

    for st in statuses:
        st["count"] = sum(1 for c in cards if c["status_id"] == st["id"])

    perms = user_perms(user)
    return jsonify(
        {
            "statuses": statuses,
            "orders": cards,
            "users": [
                {"id": u["id"], "name": u["full_name"] or u["login"], "role": u.get("role_key")}
                for u in db.query(
                    "SELECT u.id, u.full_name, u.login, r.key role_key FROM users u "
                    "LEFT JOIN roles r ON r.id=u.role_id WHERE u.active=1 ORDER BY u.full_name, u.login"
                )
            ],
            "work_types": db.query(
                "SELECT id, name_ru, name_en, active FROM work_types ORDER BY position, id"
            ),
            "permissions": sorted(perms),
            "lang": lang,
            "unread": notify.unread_count(user["id"]),
        }
    )


@bp.get("/api/meta")
@login_required
def meta():
    from ..security import current_user

    user = current_user()
    lang = db.effective_lang(user)
    return jsonify(
        {
            "statuses": oservice.statuses(),
            "users": db.query(
                "SELECT u.id, u.full_name, u.login, u.active, "
                "r.key role_key, r.name_ru role_ru, r.name_en role_en "
                "FROM users u LEFT JOIN roles r ON r.id=u.role_id ORDER BY u.full_name, u.login"
            ),
            "work_types": db.query(
                "SELECT * FROM work_types ORDER BY position, id"
            ),
            "roles": db.query("SELECT * FROM roles ORDER BY id"),
            "priorities": [
                {"key": "normal", "ru": "Обычный", "en": "Normal"},
                {"key": "urgent", "ru": "Срочный", "en": "Urgent"},
                {"key": "critical", "ru": "Критический", "en": "Critical"},
            ],
            "card_templates": db.query(
                "SELECT * FROM card_templates WHERE active=1 ORDER BY position, id"
            ),
            "cancel_reasons": (db.get_settings().get("cancel_reasons") or []),
            "ready_conditions": db.get_settings().get("ready_conditions") or {},
            "lang": lang,
            "unread": notify.unread_count(user["id"]),
            "service_name": db.get_settings().get("service_name"),
        }
    )
