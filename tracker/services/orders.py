import json

from .. import db
from ..timeutil import iso, norm_plate, norm_text, norm_vin, now, org_now
from . import checklist, notify, timetrack

CLIENT_EVENT_BY_STATUS = {
    "intake": "car_accepted",
    "approval": "approval_required",
    "work": "car_in_work",
    "parts": "parts_wait",
    "ready": "car_ready",
    "issued": "car_issued",
    "cancelled": "order_cancelled",
}

PRIORITY_KEYS = ("normal", "urgent", "critical")


def statuses(con=None) -> list[dict]:
    sql = "SELECT * FROM statuses WHERE active=1 ORDER BY position, id"
    if con is not None:
        return [dict(r) for r in con.execute(sql).fetchall()]
    return db.query(sql)


def status_by_key(key: str) -> dict | None:
    return db.one("SELECT * FROM statuses WHERE key=?", (key,))


def status_by_id(sid: int) -> dict | None:
    return db.one("SELECT * FROM statuses WHERE id=?", (sid,))


def history_add(con, order_id, user_id, action, field=None, old=None, new=None):
    con.execute(
        "INSERT INTO order_history(order_id, user_id, action, field, old_value, new_value, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            order_id,
            user_id,
            action,
            field,
            None if old is None else str(old)[:4000],
            None if new is None else str(new)[:4000],
            iso(),
        ),
    )


def next_number(con) -> str:
    year = org_now().year
    row = con.execute("SELECT value FROM counters WHERE year=?", (year,)).fetchone()
    if row:
        value = row["value"] + 1
        con.execute("UPDATE counters SET value=? WHERE year=?", (value, year))
    else:
        value = 1
        con.execute("INSERT INTO counters(year, value) VALUES(?,?)", (year, value))
    return f"{year}-{value:06d}"


def get_order(con, order_id: int) -> dict | None:
    row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return dict(row) if row else None


def open_order_count(user_id: int) -> int:
    row = db.one(
        "SELECT COUNT(*) c FROM orders o JOIN statuses s ON s.id=o.status_id "
        "WHERE o.responsible_id=? AND o.deleted=0 AND o.archive=0 "
        "AND s.key NOT IN ('issued','cancelled')",
        (user_id,),
    )
    return int(row["c"]) if row else 0


def auto_assign(con, order: dict, status: dict, user: dict) -> int | None:
    settings = db.get_settings()
    rule = settings.get("auto_assign") or {}
    if not rule.get("enabled") or order.get("responsible_id"):
        return None
    role_key = (rule.get("status_roles") or {}).get(status["key"])
    if not role_key:
        return None
    candidates = db.query(
        "SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id "
        "WHERE r.key=? AND u.active=1 AND u.role_id IS NOT NULL",
        (role_key,),
    )
    if not candidates:
        return None
    best, best_load = None, None
    for c in candidates:
        load = open_order_count(c["id"])
        if best_load is None or load < best_load:
            best, best_load = c["id"], load
    if best:
        con.execute("UPDATE orders SET responsible_id=? WHERE id=?", (best, order["id"]))
        history_add(con, order["id"], user["id"], "assign", "responsible", None, best)
    return best


def _join_plate(con, vehicle_id: int, plate: str, order_id: int):
    if not vehicle_id or not plate:
        return
    pn = norm_plate(plate)
    if not pn:
        return
    exists = con.execute(
        "SELECT id FROM vehicle_plates WHERE vehicle_id=? AND plate_norm=?",
        (vehicle_id, pn),
    ).fetchone()
    if not exists:
        con.execute(
            "INSERT INTO vehicle_plates(vehicle_id, plate_raw, plate_norm, first_seen_at, order_id) "
            "VALUES(?,?,?,?,?)",
            (vehicle_id, plate, pn, iso(), order_id),
        )


def create_order(con, data: dict, user: dict) -> dict:
    number = next_number(con)
    plate = (data.get("plate") or "").strip()
    plate_norm = norm_plate(plate)
    vin = norm_vin(data.get("vin"))
    first_status = statuses(con)[0]

    vehicle_id = data.get("vehicle_id")
    vehicle = None
    if vehicle_id:
        vehicle = con.execute(
            "SELECT * FROM vehicles WHERE id=?", (vehicle_id,)
        ).fetchone()
        vehicle = dict(vehicle) if vehicle else None
    if vehicle is None and vin:
        vehicle = con.execute(
            "SELECT * FROM vehicles WHERE vin=? ORDER BY id LIMIT 1", (vin,)
        ).fetchone()
        vehicle = dict(vehicle) if vehicle else None

    if vehicle is None:
        cur = con.execute(
            "INSERT INTO vehicles(vin, make, model, year, created_at) VALUES(?,?,?,?,?)",
            (
                vin or None,
                data.get("make") or "",
                data.get("model") or "",
                data.get("year"),
                iso(),
            ),
        )
        vehicle_id = cur.lastrowid
    else:
        vehicle_id = vehicle["id"]
        if vin and not vehicle.get("vin"):
            con.execute("UPDATE vehicles SET vin=? WHERE id=?", (vin, vehicle_id))

    make = data.get("make") or (vehicle.get("make") if vehicle else "") or ""
    model = data.get("model") or (vehicle.get("model") if vehicle else "") or ""
    year = data.get("year") or (vehicle.get("year") if vehicle else None)

    created_at = iso()
    cur = con.execute(
        "INSERT INTO orders(number, status_id, position, vehicle_id, vin, plate, plate_norm, "
        "make, model, year, client_name, client_phone, client_telegram, problem, "
        "original_works, approved_works, work_type_ids, responsible_id, priority, due_at, "
        "created_by, created_at, updated_at, updated_by) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            number,
            first_status["id"],
            _next_position(con, first_status["id"]),
            vehicle_id,
            vin,
            plate,
            plate_norm,
            make,
            model,
            year,
            data.get("client_name") or "",
            data.get("client_phone") or "",
            data.get("client_telegram") or "",
            data.get("problem") or "",
            json.dumps(data.get("original_works") or [], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            json.dumps(data.get("work_type_ids") or [], ensure_ascii=False),
            data.get("responsible_id") or None,
            data.get("priority") or "normal",
            data.get("due_at"),
            user["id"],
            created_at,
            created_at,
            user["id"],
        ),
    )
    order_id = cur.lastrowid
    _join_plate(con, vehicle_id, plate, order_id)

    work_types = data.get("work_type_ids") or []
    if work_types:
        checklist.sync_checklist(con, order_id, work_types, user["id"])
    timetrack.start_for_order(con, order_id, first_status["id"], created_at)

    order = get_order(con, order_id)
    order = dict(order)
    order["status_key"] = first_status["key"]
    auto_assign(con, order, first_status, user)
    history_add(con, order_id, user["id"], "created", "order", None, number)

    if data.get("executor_id") and data.get("status_key"):
        st = status_by_key(data["status_key"])
        if st:
            con.execute(
                "INSERT OR REPLACE INTO order_stage_executors(order_id, status_id, user_id) "
                "VALUES(?,?,?)",
                (order_id, st["id"], data["executor_id"]),
            )

    recipients = _staff_recipients(con, ("manager", "master", "admin"))
    recipients.append(order.get("responsible_id"))
    notify.notify_users(
        con,
        recipients,
        "new_order",
        {"ru": "Создан новый заказ", "en": "New order created"},
        {"ru": f"Заказ {number} · {plate}", "en": f"Order {number} · {plate}"},
        order_id,
    )
    if data.get("work_type_ids"):
        history_add(
            con,
            order_id,
            user["id"],
            "work_types",
            "work_type_ids",
            "[]",
            json.dumps(data["work_type_ids"]),
        )
    return get_order(con, order_id)


def duplicate_order(con, order: dict, user: dict) -> dict:
    data = {
        "plate": order["plate"],
        "vin": order["vin"],
        "vehicle_id": order["vehicle_id"],
        "make": order["make"],
        "model": order["model"],
        "year": order["year"],
        "client_name": order["client_name"],
        "client_phone": order["client_phone"],
        "client_telegram": order["client_telegram"],
        "problem": order["problem"],
        "original_works": json.loads(order["original_works"] or "[]"),
        "work_type_ids": json.loads(order["work_type_ids"] or "[]"),
        "priority": order["priority"],
    }
    new_order = create_order(con, data, user)
    con.execute(
        "UPDATE orders SET approved_works=? WHERE id=?",
        (order["approved_works"] or "[]", new_order["id"]),
    )
    history_add(
        con, new_order["id"], user["id"], "duplicated", "source_order", order["number"], None
    )
    return get_order(con, new_order["id"])


def _next_position(con, status_id: int) -> float:
    row = con.execute(
        "SELECT MAX(position) p FROM orders WHERE status_id=? AND deleted=0",
        (status_id,),
    ).fetchone()
    return (row["p"] or 0) + 1


def _staff_recipients(con, role_keys) -> list[int]:
    q = ",".join("?" for _ in role_keys)
    rows = con.execute(
        f"SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id "
        f"WHERE r.key IN ({q}) AND u.active=1",
        tuple(role_keys),
    ).fetchall()
    return [r["id"] for r in rows]


def stage_recipients(con, order: dict, status: dict) -> list[int]:
    ids = set()
    if order.get("responsible_id"):
        ids.add(order["responsible_id"])
    ex = con.execute(
        "SELECT user_id FROM order_stage_executors WHERE order_id=? AND status_id=?",
        (order["id"], status["id"]),
    ).fetchone()
    if ex:
        ids.add(ex["user_id"])
    return list(ids)


def apply_work_types(con, order: dict, work_type_ids, user: dict) -> dict:
    old = json.loads(order["work_type_ids"] or "[]")
    new = [int(x) for x in (work_type_ids or [])]
    con.execute(
        "UPDATE orders SET work_type_ids=?, updated_at=?, updated_by=?, version=version+1 "
        "WHERE id=?",
        (json.dumps(new), iso(), user["id"], order["id"]),
    )
    res = checklist.sync_checklist(con, order["id"], new, user["id"])
    history_add(
        con,
        order["id"],
        user["id"],
        "work_types",
        "work_type_ids",
        json.dumps(old),
        json.dumps(new),
    )
    notify.notify_users(
        con,
        stage_recipients(con, order, status_by_id(order["status_id"])),
        "checklist",
        {"ru": "Изменены типы работ", "en": "Work types changed"},
        {"ru": f"Заказ {order['number']}", "en": f"Order {order['number']}"},
        order["id"],
    )
    return res


def vin_conflicts(con, order: dict) -> list[dict]:
    vin = norm_vin(order.get("vin"))
    if not vin:
        return []
    rows = con.execute(
        "SELECT o.*, s.key status_key, s.name_ru status_ru, s.name_en status_en "
        "FROM orders o JOIN statuses s ON s.id=o.status_id "
        "WHERE o.vin=? AND o.id<>? AND o.deleted=0 ORDER BY o.created_at DESC",
        (vin, order["id"]),
    ).fetchall()
    own_vehicle = order.get("vehicle_id")
    return [
        dict(r)
        for r in rows
        if (r["vehicle_id"] if r["vehicle_id"] is not None else -1)
        != (own_vehicle if own_vehicle is not None else -2)
    ]


def attach_to_history(con, order: dict) -> list[dict]:
    conflicts = vin_conflicts(con, order)
    if conflicts:
        vid = conflicts[0].get("vehicle_id")
        if vid:
            con.execute("UPDATE orders SET vehicle_id=? WHERE id=?", (vid, order["id"]))
            if order.get("plate"):
                _join_plate(con, vid, order["plate"], order["id"])
            for row in conflicts:
                veh = con.execute(
                    "SELECT vin FROM vehicles WHERE id=?", (vid,)
                ).fetchone()
                if veh and not veh["vin"]:
                    con.execute(
                        "UPDATE vehicles SET vin=? WHERE id=?", (order["vin"], vid)
                    )
                    break
    return conflicts


def ready_problems(con, order: dict) -> list[dict]:
    settings = db.get_settings()
    cond = settings.get("ready_conditions") or {}
    problems = []
    if cond.get("vin", True):
        if not (order.get("vin") or "").strip():
            problems.append(
                {
                    "code": "vin_required",
                    "message": {"ru": "Не заполнен VIN", "en": "VIN is required"},
                }
            )
        else:
            conflicts = vin_conflicts(con, order)
            if conflicts:
                problems.append(
                    {
                        "code": "vin_conflict",
                        "message": {
                            "ru": "VIN уже существует в другой истории автомобиля",
                            "en": "VIN already exists in another vehicle history",
                        },
                        "history": [_history_entry(con, o) for o in conflicts],
                    }
                )
    if cond.get("responsible", True) and not order.get("responsible_id"):
        problems.append(
            {
                "code": "responsible_required",
                "message": {
                    "ru": "Не назначен ответственный",
                    "en": "No responsible person assigned",
                },
            }
        )
    if cond.get("checklist", True):
        missing = checklist.missing_required(order["id"])
        if missing:
            problems.append(
                {
                    "code": "checklist_incomplete",
                    "message": {
                        "ru": "Не выполнены обязательные пункты чек-листа",
                        "en": "Required checklist items are not completed",
                    },
                    "items": [m["text"] for m in missing],
                }
            )
    return problems


def _history_entry(con, o: dict) -> dict:
    responsible = None
    if o.get("responsible_id"):
        r = con.execute(
            "SELECT full_name, login FROM users WHERE id=?", (o["responsible_id"],)
        ).fetchone()
        responsible = (r["full_name"] or r["login"]) if r else None
    return {
        "id": o["id"],
        "number": o["number"],
        "created_at": o["created_at"],
        "plate": o["plate"],
        "vin": o["vin"],
        "make": o["make"],
        "model": o["model"],
        "client_name": o["client_name"],
        "client_phone": o["client_phone"],
        "problem": o["problem"],
        "status_key": o.get("status_key"),
        "status_ru": o.get("status_ru"),
        "status_en": o.get("status_en"),
        "responsible": responsible,
        "approved_works": json.loads(o.get("approved_works") or "[]"),
    }


def vin_history(con, order: dict) -> dict:
    vin = norm_vin(order.get("vin"))
    entries = []
    if vin:
        rows = con.execute(
            "SELECT o.*, s.key status_key, s.name_ru status_ru, s.name_en status_en "
            "FROM orders o JOIN statuses s ON s.id=o.status_id "
            "WHERE o.vin=? AND o.deleted=0 ORDER BY o.created_at DESC",
            (vin,),
        ).fetchall()
        entries = [_history_entry(con, dict(r)) for r in rows]
    else:
        rows = con.execute(
            "SELECT o.*, s.key status_key, s.name_ru status_ru, s.name_en status_en "
            "FROM orders o JOIN statuses s ON s.id=o.status_id WHERE o.id=?",
            (order["id"],),
        ).fetchall()
        entries = [_history_entry(con, dict(r)) for r in rows]

    plates = []
    if order.get("vehicle_id"):
        plates = [
            dict(r)
            for r in con.execute(
                "SELECT plate_raw, plate_norm, first_seen_at FROM vehicle_plates "
                "WHERE vehicle_id=? ORDER BY first_seen_at DESC",
                (order["vehicle_id"],),
            ).fetchall()
        ]
    return {"vin": vin, "orders": entries, "plates": plates}


def plate_candidates(plate: str) -> list[dict]:
    pn = norm_plate(plate)
    if not pn:
        return []
    rows = db.query(
        "SELECT vehicle_id, plate_raw, plate_norm, first_seen_at FROM vehicle_plates "
        "WHERE plate_norm=? ORDER BY first_seen_at DESC",
        (pn,),
    )
    seen, out = set(), []
    for r in rows:
        vid = r["vehicle_id"]
        if vid in seen:
            continue
        seen.add(vid)
        vehicle = db.one("SELECT * FROM vehicles WHERE id=?", (vid,))
        if not vehicle:
            continue
        last = db.one(
            "SELECT o.*, s.name_ru status_ru, s.name_en status_en, s.key status_key "
            "FROM orders o JOIN statuses s ON s.id=o.status_id "
            "WHERE o.vehicle_id=? AND o.deleted=0 ORDER BY o.created_at DESC LIMIT 1",
            (vid,),
        )
        count = db.one(
            "SELECT COUNT(*) c FROM orders WHERE vehicle_id=? AND deleted=0", (vid,)
        )["c"]
        if vehicle.get("vin"):
            extra = db.query(
                "SELECT COUNT(*) c FROM orders WHERE vin=? AND deleted=0",
                (vehicle["vin"],),
            )
            count = max(count, extra[0]["c"])
        out.append(
            {
                "vehicle_id": vid,
                "vin": vehicle.get("vin") or (last.get("vin") if last else "") or "",
                "plate": r["plate_raw"],
                "plate_norm": r["plate_norm"],
                "make": vehicle.get("make") or (last.get("make") if last else ""),
                "model": vehicle.get("model") or (last.get("model") if last else ""),
                "client_name": last.get("client_name") if last else "",
                "client_phone": last.get("client_phone") if last else "",
                "last_visit": last.get("created_at") if last else None,
                "orders_count": count,
                "order_ids": [
                    x["id"]
                    for x in db.query(
                        "SELECT id FROM orders WHERE vehicle_id=? AND deleted=0 "
                        "ORDER BY created_at DESC",
                        (vid,),
                    )
                ],
            }
        )
    return out


def move_order(
    con,
    order_id: int,
    new_status_id: int,
    user: dict,
    reason: str | None = None,
    allow_ready_override: bool = False,
) -> dict:
    order = get_order(con, order_id)
    if not order:
        return {"ok": False, "error": "not_found"}
    new_status = status_by_id(new_status_id)
    if not new_status or not new_status["active"]:
        return {"ok": False, "error": "status_not_found"}
    if order["status_id"] == new_status_id:
        return {"ok": True, "order": order, "noop": True}

    old_status = status_by_id(order["status_id"])

    if new_status["key"] == "ready" and not allow_ready_override:
        problems = ready_problems(con, order)
        if problems:
            return {"ok": False, "error": "ready_conditions", "problems": problems}

    if new_status["key"] == "cancelled":
        if not reason:
            return {"ok": False, "error": "cancel_reason_required"}

    events = []
    old_key = old_status["key"] if old_status else ""

    con.execute(
        "UPDATE orders SET status_id=?, position=?, updated_at=?, updated_by=?, "
        "version=version+1 WHERE id=?",
        (new_status_id, _next_position(con, new_status_id), iso(), user["id"], order_id),
    )
    timetrack.open_interval(con, order_id, new_status_id)

    if old_key == "cancelled" and new_status["key"] != "cancelled":
        con.execute(
            "UPDATE orders SET cancel_reason=NULL, cancel_at=NULL, cancel_by=NULL WHERE id=?",
            (order_id,),
        )

    if new_status["key"] == "approval":
        con.execute(
            "UPDATE orders SET approval_started_at=?, approval_state=NULL WHERE id=?",
            (iso(), order_id),
        )
        approvers = _staff_recipients(con, ("manager", "master", "admin"))
        notify.notify_users(
            con,
            approvers,
            "approval_request",
            {"ru": "Требуется согласование работ", "en": "Work approval required"},
            {"ru": f"Заказ {order['number']} · {order['plate']}", "en": f"Order {order['number']} · {order['plate']}"},
            order_id,
        )
        notify.notify_client(
            con,
            order,
            "approval_required",
            {"ru": "Требуется согласование работ", "en": "Work approval required"},
            {"ru": "Мы подготовили список работ и ждём вашего решения.", "en": "We have prepared the list of works and wait for your decision."},
        )

    if new_status["key"] == "parts":
        con.execute(
            "UPDATE orders SET parts_attention=0 WHERE id=?", (order_id,)
        )
        notify.notify_users(
            con,
            stage_recipients(con, order, new_status),
            "status_change",
            {"ru": "Ожидание запчастей", "en": "Waiting for parts"},
            {"ru": f"Заказ {order['number']} переведён в ожидание запчастей", "en": f"Order {order['number']} moved to waiting for parts"},
            order_id,
        )
        notify.notify_client(
            con,
            order,
            "parts_wait",
            {"ru": "Ожидание запчастей", "en": "Waiting for parts"},
            {"ru": "Ожидаем поступления запчастей.", "en": "Waiting for parts delivery."},
        )

    if new_status["key"] == "work":
        notify.notify_client(
            con,
            order,
            "car_in_work",
            {"ru": "Автомобиль в работе", "en": "Vehicle in progress"},
            {"ru": "Работы начаты.", "en": "Works started."},
        )
        if old_key == "parts":
            con.execute(
                "UPDATE orders SET parts_attention=0 WHERE id=?", (order_id,)
            )

    if new_status["key"] == "ready":
        con.execute("UPDATE orders SET parts_attention=0 WHERE id=?", (order_id,))
        recips = stage_recipients(con, order, new_status)
        notify.notify_users(
            con,
            recips,
            "car_ready",
            {"ru": "Автомобиль готов", "en": "Vehicle ready"},
            {"ru": f"Заказ {order['number']} · {order['plate']}", "en": f"Order {order['number']} · {order['plate']}"},
            order_id,
        )
        notify.notify_client(
            con,
            order,
            "car_ready",
            {"ru": "Автомобиль готов к выдаче", "en": "Vehicle ready for pickup"},
            {"ru": "Автомобиль готов, можно забирать.", "en": "The vehicle is ready for pickup."},
        )

    if new_status["key"] == "issued":
        notify.notify_client(
            con,
            order,
            "car_issued",
            {"ru": "Автомобиль выдан", "en": "Vehicle issued"},
            {"ru": "Спасибо за обращение!", "en": "Thank you for your visit!"},
        )

    if new_status["key"] == "cancelled":
        cfg_reasons = db.get_settings().get("cancel_reasons") or []
        label = reason
        for r in cfg_reasons:
            if r.get("key") == reason:
                label = r.get("ru") or reason
                break
        con.execute(
            "UPDATE orders SET cancel_reason=?, cancel_at=?, cancel_by=? WHERE id=?",
            (reason, iso(), user["id"], order_id),
        )
        notify.notify_client(
            con,
            order,
            "order_cancelled",
            {"ru": "Заказ отменён", "en": "Order cancelled"},
            {"ru": f"Причина: {label}", "en": f"Reason: {label}"},
        )

    if new_status["key"] == "intake":
        notify.notify_client(
            con,
            order,
            "car_accepted",
            {"ru": "Автомобиль принят", "en": "Vehicle accepted"},
            {"ru": "Мы приняли ваш автомобиль.", "en": "We have accepted your vehicle."},
        )

    if not order.get("responsible_id"):
        auto_assign(con, get_order(con, order_id), new_status, user)

    history_add(
        con,
        order_id,
        user["id"],
        "status_change",
        "status",
        old_status["name_ru"] if old_status else old_key,
        new_status["name_ru"],
    )

    recips = stage_recipients(con, get_order(con, order_id), new_status)
    if user["id"] not in recips:
        notify.notify_users(
            con,
            recips,
            "status_change",
            {"ru": "Изменён этап заказа", "en": "Order stage changed"},
            {
                "ru": f"Заказ {order['number']}: {new_status['name_ru']}",
                "en": f"Order {order['number']}: {new_status['name_en']}",
            },
            order_id,
        )

    return {"ok": True, "order": get_order(con, order_id), "events": events}


def set_responsible(con, order: dict, responsible_id, user: dict):
    old = order.get("responsible_id")
    if old == responsible_id:
        return
    con.execute(
        "UPDATE orders SET responsible_id=?, updated_at=?, updated_by=?, version=version+1 "
        "WHERE id=?",
        (responsible_id, iso(), user["id"], order["id"]),
    )
    history_add(
        con, order["id"], user["id"], "assign", "responsible", old, responsible_id
    )
    recips = []
    if responsible_id:
        recips.append(responsible_id)
    notify.notify_users(
        con,
        recips,
        "assign",
        {"ru": "Вы назначены ответственным", "en": "You are assigned as responsible"},
        {"ru": f"Заказ {order['number']} · {order['plate']}", "en": f"Order {order['number']} · {order['plate']}"},
        order["id"],
    )
    if old:
        notify.notify_users(
            con,
            [old],
            "responsible_change",
            {"ru": "Ответственный изменён", "en": "Responsible changed"},
            {"ru": f"Заказ {order['number']}", "en": f"Order {order['number']}"},
            order["id"],
        )


def set_priority(con, order: dict, priority: str, user: dict):
    if priority not in PRIORITY_KEYS or order["priority"] == priority:
        return
    con.execute(
        "UPDATE orders SET priority=?, updated_at=?, updated_by=?, version=version+1 WHERE id=?",
        (priority, iso(), user["id"], order["id"]),
    )
    history_add(
        con, order["id"], user["id"], "priority", "priority", order["priority"], priority
    )
    notify.notify_users(
        con,
        stage_recipients(con, order, status_by_id(order["status_id"])),
        "priority_change",
        {"ru": "Изменён приоритет", "en": "Priority changed"},
        {"ru": f"Заказ {order['number']}: {priority}", "en": f"Order {order['number']}: {priority}"},
        order["id"],
    )


def set_due(con, order: dict, due_at, user: dict):
    con.execute(
        "UPDATE orders SET due_at=?, updated_at=?, updated_by=?, version=version+1 WHERE id=?",
        (due_at, iso(), user["id"], order["id"]),
    )
    history_add(
        con, order["id"], user["id"], "due", "due_at", order.get("due_at"), due_at
    )


def approval_set(con, order: dict, decision: str, items, user: dict) -> dict:
    approved = []
    for it in items or []:
        approved.append(
            {"text": it.get("text", ""), "state": it.get("state", "approved")}
        )
    if decision == "approved":
        for a in approved:
            a["state"] = "approved"
    con.execute(
        "UPDATE orders SET approved_works=?, approval_state=?, updated_at=?, updated_by=?, "
        "version=version+1 WHERE id=?",
        (
            json.dumps(approved, ensure_ascii=False),
            {"approved": "full", "partial": "partial", "rejected": "rejected"}.get(
                decision, "partial"
            ),
            iso(),
            user["id"],
            order["id"],
        ),
    )
    history_add(
        con,
        order["id"],
        user["id"],
        "approval",
        "approval_state",
        order.get("approval_state"),
        decision,
    )
    approved_n = sum(1 for a in approved if a["state"] == "approved")
    notify.notify_client(
        con,
        order,
        "approval_result",
        {
            "ru": "Результат согласования",
            "en": "Approval result",
        },
        {
            "ru": {
                "approved": "Все работы согласованы.",
                "partial": f"Согласовано работ: {approved_n} из {len(approved)}.",
                "rejected": "Работы не согласованы.",
            }.get(decision, ""),
            "en": {
                "approved": "All works approved.",
                "partial": f"Approved works: {approved_n} of {len(approved)}.",
                "rejected": "Works rejected.",
            }.get(decision, ""),
        },
    )

    if decision == "approved":
        st = status_by_key("work")
        if st:
            return move_order(con, order["id"], st["id"], user, allow_ready_override=True)
    if decision == "rejected":
        st = status_by_key("cancelled")
        if st:
            return move_order(
                con,
                order["id"],
                st["id"],
                user,
                reason="approval_rejected",
                allow_ready_override=True,
            )
    return {"ok": True, "order": get_order(con, order["id"])}


def set_executor(con, order: dict, status_id: int, executor_id, user: dict):
    if executor_id:
        con.execute(
            "INSERT OR REPLACE INTO order_stage_executors(order_id, status_id, user_id) "
            "VALUES(?,?,?)",
            (order["id"], status_id, executor_id),
        )
        notify.notify_users(
            con,
            [executor_id],
            "assign",
            {"ru": "Вы назначены исполнителем этапа", "en": "You are assigned as stage executor"},
            {"ru": f"Заказ {order['number']} · {order['plate']}", "en": f"Order {order['number']} · {order['plate']}"},
            order["id"],
        )
    else:
        con.execute(
            "DELETE FROM order_stage_executors WHERE order_id=? AND status_id=?",
            (order["id"], status_id),
        )
    history_add(
        con, order["id"], user["id"], "executor", str(status_id), None, executor_id
    )


def full_order(con, order_id: int, lang: str = "ru") -> dict | None:
    order = get_order(con, order_id)
    if not order:
        return None
    status = status_by_id(order["status_id"])
    responsible = None
    if order.get("responsible_id"):
        u = con.execute(
            "SELECT id, full_name, login, telegram_chat_id FROM users WHERE id=?",
            (order["responsible_id"],),
        ).fetchone()
        if u:
            responsible = {
                "id": u["id"],
                "name": u["full_name"] or u["login"],
                "telegram": bool(u["telegram_chat_id"]),
            }
    executors = {
        str(r["status_id"]): r["user_id"]
        for r in con.execute(
            "SELECT * FROM order_stage_executors WHERE order_id=?", (order_id,)
        ).fetchall()
    }
    users = {
        str(u["id"]): (u["full_name"] or u["login"])
        for u in con.execute("SELECT id, full_name, login FROM users").fetchall()
    }
    work_types = {
        str(w["id"]): (w["name_ru"] if lang == "ru" else w["name_en"])
        for w in con.execute("SELECT * FROM work_types").fetchall()
    }
    cancel_reasons = db.get_settings().get("cancel_reasons") or []
    cancel_label = order.get("cancel_reason")
    for r in cancel_reasons:
        if r.get("key") == order.get("cancel_reason"):
            cancel_label = r.get(lang) or r.get("ru")
    return {
        **order,
        "archive": bool(order["archive"]),
        "deleted": bool(order["deleted"]),
        "parts_attention": bool(order["parts_attention"]),
        "work_type_ids": json.loads(order["work_type_ids"] or "[]"),
        "status": status,
        "responsible_name": responsible["name"] if responsible else None,
        "responsible": responsible,
        "executors": executors,
        "users": users,
        "work_types": [
            {
                "id": int(wid),
                "name": work_types.get(str(wid), wid),
            }
            for wid in json.loads(order["work_type_ids"] or "[]")
        ],
        "original_works": json.loads(order["original_works"] or "[]"),
        "approved_works": json.loads(order["approved_works"] or "[]"),
        "checklist": checklist.items_for(order_id),
        "checklist_progress": checklist.progress(order_id),
        "cancel_reason_label": cancel_label,
        "client_binding": db.one(
            "SELECT code, telegram_chat_id, bound_at FROM client_bindings "
            "WHERE order_id=? ORDER BY id DESC LIMIT 1",
            (order_id,),
        ),
        "ready_problems": ready_problems(con, order)
        if status and status["key"] not in ("issued", "cancelled")
        else [],
    }
