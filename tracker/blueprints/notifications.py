import json

from flask import Blueprint, jsonify, request

from .. import db
from ..security import current_user, login_required
from ..services import notify
from ..timeutil import iso

bp = Blueprint("notifications", __name__)


def _serialize(n: dict, lang: str) -> dict:
    def txt(value):
        if not value:
            return ""
        try:
            data = json.loads(value)
            if isinstance(data, dict):
                return data.get(lang) or data.get("ru") or ""
            return str(value)
        except (ValueError, TypeError):
            return str(value)

    return {
        "id": n["id"],
        "type": n["type"],
        "type_label": notify.type_label(n["type"], lang),
        "order_id": n["order_id"],
        "title": txt(n["title"]),
        "body": txt(n["body"]),
        "link": n["link"],
        "read": bool(n["read_at"]),
        "created_at": n["created_at"],
    }


@bp.get("/api/notifications")
@login_required
def list_notifications():
    user = current_user()
    lang = db.effective_lang(user)
    flt = request.args.get("filter") or "all"
    limit = min(int(request.args.get("limit") or 50), 200)
    sql = "SELECT * FROM notifications WHERE user_id=?"
    args = [user["id"]]
    if flt == "unread":
        sql += " AND read_at IS NULL"
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = db.query(sql, args)
    return jsonify(
        {
            "notifications": [_serialize(r, lang) for r in rows],
            "unread": notify.unread_count(user["id"]),
        }
    )


@bp.post("/api/notifications/read")
@login_required
def read_notifications():
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    notify.mark_read(user["id"], data.get("ids"))
    return jsonify({"unread": notify.unread_count(user["id"])})


@bp.get("/api/notifications/unread-count")
@login_required
def unread():
    user = current_user()
    return jsonify({"unread": notify.unread_count(user["id"])})
