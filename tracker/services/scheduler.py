import json
import threading
import time

from .. import db
from ..timeutil import iso, now, org_now, parse
from . import backup, notify, telegram

_thread = None
_stop = threading.Event()


def start_scheduler():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="tracker-scheduler")
    _thread.start()


def stop_scheduler():
    _stop.set()


def _loop():
    while not _stop.is_set():
        try:
            tick()
        except Exception as exc:
            print(f"[scheduler] error: {exc}")
        _stop.wait(30)


def tick():
    _telegram_poll()
    _parts_attention()
    _due_and_overdue()
    _daily_backup()


def _notify_orders(con, order, type_key, title, body, recipients):
    notify.notify_users(
        con, recipients, type_key, title, body, order["id"]
    )


def _due_and_overdue():
    settings = db.get_settings()
    overdue_repeat = float(settings.get("overdue_repeat_hours", 6) or 6)
    due_soon_hours = float(settings.get("due_soon_hours", 24) or 24)
    overdue_map = dict(settings.get("overdue_notified_at") or {})
    due_map = dict(settings.get("due_notified_at") or {})
    changed = False

    rows = db.query(
        "SELECT o.*, s.key status_key FROM orders o JOIN statuses s ON s.id=o.status_id "
        "WHERE o.deleted=0 AND o.archive=0 AND o.due_at IS NOT NULL "
        "AND s.key NOT IN ('issued','cancelled')"
    )
    t = now()
    for o in rows:
        due = parse(o["due_at"])
        if not due:
            continue
        if due < t:
            last = parse(overdue_map.get(str(o["id"])))
            if not last or (t - last).total_seconds() >= overdue_repeat * 3600:
                overdue_map[str(o["id"])] = iso()
                changed = True
                recipients = [o["responsible_id"], o["created_by"]] if o.get("responsible_id") else [o["created_by"]]
                admins = db.query(
                    "SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id "
                    "WHERE r.key IN ('master','admin') AND u.active=1"
                )
                recipients += [a["id"] for a in admins]
                con = db.connect()
                try:
                    notify.notify_users(
                        con,
                        recipients,
                        "overdue",
                        {"ru": "Просрочка по сроку", "en": "Overdue"},
                        {
                            "ru": f"Заказ {o['number']} · {o['plate']} просрочен",
                            "en": f"Order {o['number']} · {o['plate']} is overdue",
                        },
                        o["id"],
                    )
                    con.commit()
                finally:
                    con.close()
        elif (due - t).total_seconds() <= due_soon_hours * 3600:
            if str(o["id"]) not in due_map:
                due_map[str(o["id"])] = iso()
                changed = True
                con = db.connect()
                try:
                    notify.notify_users(
                        con,
                        [o["responsible_id"]],
                        "due_soon",
                        {"ru": "Приближается срок", "en": "Due date approaching"},
                        {
                            "ru": f"Заказ {o['number']} · {o['plate']} — срок скоро",
                            "en": f"Order {o['number']} · {o['plate']} — due soon",
                        },
                        o["id"],
                    )
                    con.commit()
                finally:
                    con.close()

    live_ids = {str(r["id"]) for r in rows}
    overdue_map = {k: v for k, v in overdue_map.items() if k in live_ids}
    due_map = {k: v for k, v in due_map.items() if k in live_ids}
    if changed or True:
        db.set_setting("overdue_notified_at", overdue_map)
        db.set_setting("due_notified_at", due_map)


def _parts_attention():
    rows = db.query(
        "SELECT o.*, s.key status_key FROM orders o JOIN statuses s ON s.id=o.status_id "
        "WHERE o.deleted=0 AND s.key='parts' AND o.parts_attention=0 "
        "AND o.parts_expected_at IS NOT NULL"
    )
    t = now()
    for o in rows:
        exp = parse(o["parts_expected_at"])
        if exp and exp <= t:
            con = db.connect()
            try:
                con.execute(
                    "UPDATE orders SET parts_attention=1 WHERE id=?", (o["id"],)
                )
                con.execute(
                    "INSERT INTO order_history(order_id, user_id, action, field, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (o["id"], None, "parts_attention", "parts_expected_at", iso()),
                )
                notify.notify_users(
                    con,
                    [o["responsible_id"]],
                    "system",
                    {
                        "ru": "Дата поступления запчастей наступила",
                        "en": "Parts arrival date has come",
                    },
                    {
                        "ru": f"Заказ {o['number']} всё ещё в ожидании запчастей",
                        "en": f"Order {o['number']} is still waiting for parts",
                    },
                    o["id"],
                )
                con.commit()
            finally:
                con.close()


def _daily_backup():
    settings = db.get_settings()
    target = str(settings.get("backup_time", "03:00"))
    local = org_now()
    if local.strftime("%H:%M") < target:
        return
    if backup.backup_today_exists("daily"):
        return
    backup.create_backup("daily")


def _telegram_poll():
    try:
        telegram.poll_updates()
    except Exception:
        pass
