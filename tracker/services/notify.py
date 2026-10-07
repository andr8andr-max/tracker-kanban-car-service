import json
import threading
from contextlib import contextmanager

from .. import db
from ..timeutil import iso
from . import telegram

_quiet = False


@contextmanager
def quiet():
    """Подавляет создание уведомлений (используется при сидировании демо-данных)."""
    global _quiet
    prev = _quiet
    _quiet = True
    try:
        yield
    finally:
        _quiet = prev


EMPLOYEE_TYPES = [
    {"key": "assign", "ru": "Назначение в заказ", "en": "Assigned to order"},
    {"key": "status_change", "ru": "Изменение этапа", "en": "Stage changed"},
    {"key": "responsible_change", "ru": "Изменение ответственного", "en": "Responsible changed"},
    {"key": "due_soon", "ru": "Приближение срока", "en": "Due date approaching"},
    {"key": "overdue", "ru": "Просрочка", "en": "Overdue"},
    {"key": "comment", "ru": "Новый комментарий", "en": "New comment"},
    {"key": "priority_change", "ru": "Изменение приоритета", "en": "Priority changed"},
    {"key": "checklist", "ru": "Чек-лист", "en": "Checklist"},
    {"key": "new_order", "ru": "Новый заказ", "en": "New order"},
    {"key": "car_ready", "ru": "Автомобиль готов", "en": "Vehicle ready"},
    {"key": "system", "ru": "Системные уведомления", "en": "System notifications"},
    {"key": "approval_request", "ru": "Требуется согласование", "en": "Approval required"},
]

CLIENT_TYPES = [
    {"key": "car_accepted", "ru": "Автомобиль принят", "en": "Vehicle accepted"},
    {"key": "approval_required", "ru": "Требуется согласование", "en": "Approval required"},
    {"key": "approval_result", "ru": "Результат согласования", "en": "Approval result"},
    {"key": "car_in_work", "ru": "Автомобиль в работе", "en": "Vehicle in progress"},
    {"key": "parts_wait", "ru": "Ожидание запчастей", "en": "Waiting for parts"},
    {"key": "car_ready", "ru": "Автомобиль готов", "en": "Vehicle ready"},
    {"key": "car_issued", "ru": "Автомобиль выдан", "en": "Vehicle issued"},
    {"key": "order_cancelled", "ru": "Заказ отменён", "en": "Order cancelled"},
]

ALL_TYPES = {t["key"]: t for t in EMPLOYEE_TYPES + CLIENT_TYPES}


def type_label(key: str, lang: str = "ru") -> str:
    t = ALL_TYPES.get(key, {})
    return t.get(lang) or t.get("ru") or key


def type_enabled_for_role(type_key: str, role_key: str | None) -> bool:
    matrix = db.get_settings().get("notify_matrix") or {}
    per_type = matrix.get(type_key)
    if per_type is None:
        return True
    if role_key is None:
        return True
    return bool(per_type.get(role_key, True))


def _exec(con, sql: str, args=()):
    if con is not None:
        return con.execute(sql, args).lastrowid
    return db.execute(sql, args)


def _one(con, sql: str, args=()) -> dict | None:
    if con is not None:
        row = con.execute(sql, args).fetchone()
        return dict(row) if row else None
    return db.one(sql, args)


def _role_key(con, user_id: int) -> str | None:
    row = _one(
        con,
        "SELECT r.key FROM users u LEFT JOIN roles r ON r.id=u.role_id WHERE u.id=?",
        (user_id,),
    )
    return row["key"] if row else None


def notify_users(
    con,
    user_ids,
    type_key: str,
    title: dict,
    body: dict | str = "",
    order_id=None,
    link: str = "",
):
    if _quiet:
        return
    ids = {u for u in (user_ids or []) if u}
    if not ids:
        return
    roles = {uid: _role_key(con, uid) for uid in ids}
    for uid in sorted(ids):
        if not type_enabled_for_role(type_key, roles.get(uid)):
            continue
        _exec(
            con,
            "INSERT INTO notifications(user_id, type, order_id, title, body, link, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                uid,
                type_key,
                order_id,
                json.dumps(title, ensure_ascii=False),
                json.dumps(body, ensure_ascii=False)
                if isinstance(body, dict)
                else (body or ""),
                link or (f"#/order/{order_id}" if order_id else ""),
                iso(),
            ),
        )
        user = _one(
            con,
            "SELECT lang, lang_custom, telegram_chat_id FROM users WHERE id=?",
            (uid,),
        )
        if user and user.get("telegram_chat_id"):
            lang = db.effective_lang(user)
            text = f"<b>{title.get(lang) or title.get('ru')}</b>"
            if body:
                if isinstance(body, dict):
                    text += "\n" + (body.get(lang) or body.get("ru") or "")
                else:
                    text += "\n" + str(body)
            chat_id = user["telegram_chat_id"]
            threading.Thread(
                target=telegram.send, args=(chat_id, text), daemon=True
            ).start()


def notify_client(con, order: dict, type_key: str, title: dict, body: dict | str = ""):
    if _quiet:
        return
    binding = _one(
        con,
        "SELECT telegram_chat_id FROM client_bindings "
        "WHERE order_id=? AND bound_at IS NOT NULL ORDER BY id DESC LIMIT 1",
        (order.get("id"),),
    )
    chat_id = binding.get("telegram_chat_id") if binding else None
    if not chat_id:
        return
    text = f"<b>{title.get('ru')}</b>"
    if body:
        text += "\n" + (body.get("ru") if isinstance(body, dict) else str(body))
    text += f"\nЗаказ {order.get('number', '')}"
    threading.Thread(target=telegram.send, args=(chat_id, text), daemon=True).start()


def unread_count(user_id: int) -> int:
    row = db.one(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND read_at IS NULL",
        (user_id,),
    )
    return int(row["c"]) if row else 0


def mark_read(user_id: int, ids=None):
    if ids is None:
        db.execute(
            "UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
            (iso(), user_id),
        )
        return
    clean = []
    if isinstance(ids, list):
        for i in ids[:500]:
            try:
                clean.append(int(i))
            except (TypeError, ValueError):
                continue
    if not clean:
        return
    q = ",".join("?" for _ in clean)
    db.execute(
        f"UPDATE notifications SET read_at=? WHERE user_id=? AND id IN ({q})",
        (iso(), user_id, *clean),
    )
