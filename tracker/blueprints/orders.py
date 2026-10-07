import json

from flask import Blueprint, jsonify, request

from .. import db
from ..security import audit, current_user, has_perm, login_required, permission_required, user_perms
from ..services import checklist, notify, orders as oservice, timetrack
from ..timeutil import iso, norm_plate, norm_vin, now, parse

bp = Blueprint("orders", __name__)


def _err(message, code="error", status=400, **extra):
    payload = {"error": code, "message": message}
    payload.update(extra)
    return jsonify(payload), status


def _open():
    return db.connect()


def _lang(user=None):
    u = user or current_user()
    return db.effective_lang(u) if u else "ru"


@bp.get("/api/orders/search-plate")
@login_required
def search_plate():
    plate = request.args.get("plate") or ""
    return jsonify({"candidates": oservice.plate_candidates(plate)})


@bp.post("/api/orders")
@permission_required("order.create")
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    plate = (data.get("plate") or "").strip()
    if not plate:
        return _err("Госномер обязателен", "plate_required")
    candidates = oservice.plate_candidates(plate)
    vehicle_id = data.get("vehicle_id")
    no_merge = bool(data.get("no_merge"))
    if candidates and not vehicle_id and not no_merge:
        return (
            jsonify(
                {
                    "error": "merge_choice_required",
                    "message": "Выберите историю автомобиля или «Не объединять»",
                    "candidates": candidates,
                }
            ),
            409,
        )
    payload = dict(data)
    if no_merge:
        payload["vehicle_id"] = None
        payload["vin"] = payload.get("vin") or ""
        if payload.get("vin"):
            existing = db.query(
                "SELECT id FROM vehicles WHERE vin=?", (norm_vin(payload["vin"]),)
            )
            if existing:
                payload["vehicle_id"] = existing[0]["id"]
    con = _open()
    try:
        order = oservice.create_order(con, payload, user)
        con.commit()
        audit("order_create", "order", order["number"], plate)
        return jsonify({"order": _full(con, order["id"])}), 201
    finally:
        con.close()


@bp.get("/api/orders/<int:order_id>")
@login_required
def get_order(order_id):
    con = _open()
    try:
        order = oservice.full_order(con, order_id, _lang())
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        if order["deleted"]:
            return _err("Заказ удалён", "deleted", 410)
        data = _full(con, order_id, order=order)
        perms = user_perms(current_user())
        data["permissions"] = sorted(perms)
        data["time"] = timetrack.totals(order_id)
        data["comments"] = _comments(order_id)
        data["history"] = _history(order_id)
        data["vin_history"] = oservice.vin_history(con, order)["orders"] if order.get("vin") else []
        data["plates"] = oservice.vin_history(con, order)["plates"]
        return jsonify({"order": data})
    finally:
        con.close()


def _full(con, order_id, order=None):
    lang = _lang()
    order = order or oservice.full_order(con, order_id, lang)
    return order


def _comments(order_id):
    rows = db.query(
        "SELECT c.*, u.full_name, u.login FROM order_comments c "
        "JOIN users u ON u.id=c.user_id WHERE c.order_id=? AND c.deleted=0 "
        "ORDER BY c.created_at",
        (order_id,),
    )
    return rows


def _history(order_id):
    rows = db.query(
        "SELECT h.*, u.full_name, u.login FROM order_history h "
        "LEFT JOIN users u ON u.id=h.user_id WHERE h.order_id=? "
        "ORDER BY h.created_at DESC, h.id DESC",
        (order_id,),
    )
    return rows


@bp.put("/api/orders/<int:order_id>")
@permission_required("order.edit")
def update_order(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order or order["deleted"]:
            return _err("Заказ не найден", "not_found", 404)

        fields = {
            "make": "make",
            "model": "model",
            "client_name": "client_name",
            "client_phone": "client_phone",
            "client_telegram": "client_telegram",
            "problem": "problem",
        }
        for key, col in fields.items():
            if key in data:
                con.execute(
                    f"UPDATE orders SET {col}=? WHERE id=?", (data[key] or "", order_id)
                )
                oservice.history_add(con, order_id, user["id"], "field", col, order.get(col), data[key])

        if "year" in data:
            con.execute("UPDATE orders SET year=? WHERE id=?", (data.get("year"), order_id))

        if "due_at" in data and has_perm(user, "order.due"):
            oservice.set_due(con, order, data.get("due_at"), user)

        if "vin" in data and has_perm(user, "order.edit"):
            vin = norm_vin(data.get("vin"))
            if vin != (order.get("vin") or ""):
                con.execute("UPDATE orders SET vin=? WHERE id=?", (vin, order_id))
                oservice.history_add(con, order_id, user["id"], "field", "vin", order.get("vin"), vin)
                if vin and order.get("vehicle_id"):
                    veh = con.execute(
                        "SELECT vin FROM vehicles WHERE id=?", (order["vehicle_id"],)
                    ).fetchone()
                    other = con.execute(
                        "SELECT id FROM vehicles WHERE vin=? AND id<>?", (vin, order["vehicle_id"])
                    ).fetchone()
                    if veh and not veh["vin"] and not other:
                        con.execute(
                            "UPDATE vehicles SET vin=? WHERE id=?", (vin, order["vehicle_id"])
                        )

        if "plate" in data:
            plate = (data.get("plate") or "").strip()
            pn = norm_plate(plate)
            if pn != order["plate_norm"]:
                con.execute(
                    "UPDATE orders SET plate=?, plate_norm=? WHERE id=?",
                    (plate, pn, order_id),
                )
                oservice.history_add(
                    con, order_id, user["id"], "field", "plate", order.get("plate"), plate
                )
                if order.get("vehicle_id") and pn:
                    oservice._join_plate(con, order["vehicle_id"], plate, order_id)

        if "original_works" in data:
            val = data.get("original_works") or []
            con.execute(
                "UPDATE orders SET original_works=? WHERE id=?",
                (json.dumps(val, ensure_ascii=False), order_id),
            )
            oservice.history_add(
                con,
                order_id,
                user["id"],
                "field",
                "original_works",
                order.get("original_works"),
                json.dumps(val, ensure_ascii=False),
            )

        con.execute(
            "UPDATE orders SET updated_at=?, updated_by=?, version=version+1 WHERE id=?",
            (iso(), user["id"], order_id),
        )
        con.commit()
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/move")
@login_required
def move_order(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.move"):
        return _err("Forbidden: order.move", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order or order["deleted"]:
            return _err("Заказ не найден", "not_found", 404)
        if data.get("version") is not None and int(data["version"]) != order["version"]:
            cur = oservice.full_order(con, order_id, _lang())
            return (
                jsonify(
                    {
                        "error": "version_conflict",
                        "message": "Карточка изменена другим пользователем",
                        "current": cur,
                    }
                ),
                409,
            )
        target_id = int(data.get("status_id") or 0)
        accept_merge = bool(data.get("accept_vin_merge"))
        result = oservice.move_order(
            con,
            order_id,
            target_id,
            user,
            reason=data.get("reason"),
            allow_ready_override=accept_merge,
        )
        if not result.get("ok"):
            if result.get("error") == "ready_conditions":
                status = oservice.status_by_id(target_id)
                return (
                    jsonify(
                        {
                            "error": "ready_conditions",
                            "problems": result["problems"],
                            "status": status,
                        }
                    ),
                    422,
                )
            return _err(result.get("error"), result.get("error", "error"), 400)
        if accept_merge:
            oservice.attach_to_history(con, order)
            oservice.history_add(
                con, order_id, user["id"], "vin_merged", "vin", None, order.get("vin")
            )
        con.commit()
        audit("order_move", "order", order_id, f"status={target_id}")
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/priority")
@login_required
def set_priority(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.priority"):
        return _err("Forbidden: order.priority", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        oservice.set_priority(con, order, data.get("priority") or "normal", user)
        con.commit()
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/responsible")
@login_required
def set_responsible(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.assign"):
        return _err("Forbidden: order.assign", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        rid = data.get("user_id")
        oservice.set_responsible(con, order, rid, user)
        con.commit()
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/executor")
@login_required
def set_executor(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.assign"):
        return _err("Forbidden: order.assign", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        st = oservice.status_by_id(int(data.get("status_id") or 0))
        if not st:
            return _err("Статус не найден", "status_not_found", 404)
        oservice.set_executor(con, order, st["id"], data.get("user_id"), user)
        con.commit()
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/worktypes")
@login_required
def set_worktypes(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.worktypes"):
        return _err("Forbidden: order.worktypes", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        status = oservice.status_by_id(order["status_id"])
        if status and status["key"] == "appointment":
            return _err(
                "Типы работ выбираются после этапа «Диагностика»",
                "too_early",
                400,
            )
        res = oservice.apply_work_types(con, order, data.get("ids") or [], user)
        con.commit()
        return jsonify({"order": _full(con, order_id), "sync": res})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/approval")
@login_required
def approval(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.approve"):
        return _err("Forbidden: order.approve", "forbidden", 403)
    decision = data.get("decision")
    if decision not in ("approved", "partial", "rejected"):
        return _err("Некорректное решение", "bad_decision")
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        items = data.get("items")
        if not items:
            items = [
                {"text": w.get("text", ""), "state": "approved"}
                for w in json.loads(order["original_works"] or "[]")
            ]
        result = oservice.approval_set(con, order, decision, items, user)
        if not result.get("ok"):
            if result.get("error") == "ready_conditions":
                return jsonify({"error": "ready_conditions", "problems": result["problems"]}), 422
            return _err(result.get("error"), result.get("error", "error"))
        con.commit()
        audit("order_approval", "order", order_id, decision)
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/checklist/toggle")
@login_required
def checklist_toggle(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.checklist"):
        return _err("Forbidden: order.checklist", "forbidden", 403)
    con = _open()
    try:
        item = con.execute(
            "SELECT * FROM order_checklist_items WHERE id=? AND order_id=?",
            (int(data.get("item_id") or 0), order_id),
        ).fetchone()
        if not item:
            return _err("Пункт не найден", "not_found", 404)
        done = bool(data.get("done"))
        checklist.set_done(con, item["id"], user["id"], done)
        order = oservice.get_order(con, order_id)
        oservice.history_add(
            con,
            order_id,
            user["id"],
            "checklist_toggle",
            item["text"],
            item["done"],
            int(done),
        )
        notify.notify_users(
            con,
            oservice.stage_recipients(
                con, order, oservice.status_by_id(order["status_id"])
            ),
            "checklist",
            {"ru": "Чек-лист обновлён", "en": "Checklist updated"},
            {
                "ru": f"«{item['text']}» — {'выполнено' if done else 'снято'} · {order['number']}",
                "en": f"«{item['text']}» — {'done' if done else 'undone'} · {order['number']}",
            },
            order_id,
        )
        con.commit()
        full = oservice.full_order(con, order_id, _lang())
        return jsonify(
            {
                "checklist": full["checklist"],
                "progress": full["checklist_progress"],
                "ready_problems": full["ready_problems"],
            }
        )
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/checklist/item")
@login_required
def checklist_add(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.checklist"):
        return _err("Forbidden: order.checklist", "forbidden", 403)
    text = (data.get("text") or "").strip()
    if not text:
        return _err("Пустой пункт", "empty")
    from ..timeutil import norm_text

    con = _open()
    try:
        exists = con.execute(
            "SELECT id FROM order_checklist_items WHERE order_id=? AND text_norm=?",
            (order_id, norm_text(text)),
        ).fetchone()
        if exists:
            return _err("Такой пункт уже есть", "duplicate", 409)
        con.execute(
            "INSERT INTO order_checklist_items(order_id, text, text_norm, stage_key, required, "
            "done, work_type_ids, position) VALUES(?,?,?,?,?,0,'[]',?)",
            (
                order_id,
                text,
                norm_text(text),
                data.get("stage_key") or "",
                1 if data.get("required", True) else 0,
                con.execute(
                    "SELECT COALESCE(MAX(position),0)+1 p FROM order_checklist_items "
                    "WHERE order_id=?",
                    (order_id,),
                ).fetchone()["p"],
            ),
        )
        oservice.history_add(con, order_id, user["id"], "checklist_add", text, None, 1)
        con.commit()
        full = oservice.full_order(con, order_id, _lang())
        return jsonify({"checklist": full["checklist"], "progress": full["checklist_progress"]})
    finally:
        con.close()


@bp.put("/api/orders/<int:order_id>/checklist/item/<int:item_id>")
@login_required
def checklist_update(order_id, item_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.checklist"):
        return _err("Forbidden: order.checklist", "forbidden", 403)
    con = _open()
    try:
        item = con.execute(
            "SELECT * FROM order_checklist_items WHERE id=? AND order_id=?",
            (item_id, order_id),
        ).fetchone()
        if not item:
            return _err("Пункт не найден", "not_found", 404)
        if "text" in data:
            new_text = (data.get("text") or "").strip()
            if new_text:
                con.execute(
                    "UPDATE order_checklist_items SET text=?, text_norm=? WHERE id=?",
                    (new_text, __import__("tracker.timeutil", fromlist=["norm_text"]).norm_text(new_text), item_id),
                )
                oservice.history_add(con, order_id, user["id"], "checklist_edit", item["text"], new_text)
        if "required" in data and has_perm(user, "order.checklist.required"):
            con.execute(
                "UPDATE order_checklist_items SET required=? WHERE id=?",
                (1 if data.get("required") else 0, item_id),
            )
            oservice.history_add(
                con,
                order_id,
                user["id"],
                "checklist_required",
                item["text"],
                item["required"],
                int(bool(data.get("required"))),
            )
        con.commit()
        full = oservice.full_order(con, order_id, _lang())
        return jsonify({"checklist": full["checklist"], "progress": full["checklist_progress"]})
    finally:
        con.close()


@bp.delete("/api/orders/<int:order_id>/checklist/item/<int:item_id>")
@login_required
def checklist_delete(order_id, item_id):
    user = current_user()
    if not has_perm(user, "order.checklist"):
        return _err("Forbidden: order.checklist", "forbidden", 403)
    con = _open()
    try:
        item = con.execute(
            "SELECT * FROM order_checklist_items WHERE id=? AND order_id=?",
            (item_id, order_id),
        ).fetchone()
        if not item:
            return _err("Пункт не найден", "not_found", 404)
        con.execute("DELETE FROM order_checklist_items WHERE id=?", (item_id,))
        oservice.history_add(con, order_id, user["id"], "checklist_delete", item["text"], 1, None)
        con.commit()
        full = oservice.full_order(con, order_id, _lang())
        return jsonify({"checklist": full["checklist"], "progress": full["checklist_progress"]})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/comments")
@permission_required("order.comment")
def add_comment(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    text = (data.get("text") or "").strip()
    if not text:
        return _err("Пустой комментарий", "empty")
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        con.execute(
            "INSERT INTO order_comments(order_id, user_id, text, created_at) VALUES(?,?,?,?)",
            (order_id, user["id"], text, iso()),
        )
        oservice.history_add(con, order_id, user["id"], "comment", None, None, text[:200])
        recipients = oservice.stage_recipients(
            con, order, oservice.status_by_id(order["status_id"])
        )
        notify.notify_users(
            con,
            recipients,
            "comment",
            {"ru": "Новый комментарий", "en": "New comment"},
            {"ru": f"{user['full_name'] or user['login']}: {text[:200]}", "en": text[:200]},
            order_id,
        )
        con.commit()
        return jsonify({"comments": _comments(order_id)}), 201
    finally:
        con.close()


@bp.put("/api/orders/<int:order_id>/comments/<int:comment_id>")
@login_required
def edit_comment(order_id, comment_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    con = _open()
    try:
        c = con.execute(
            "SELECT * FROM order_comments WHERE id=? AND order_id=?",
            (comment_id, order_id),
        ).fetchone()
        if not c:
            return _err("Комментарий не найден", "not_found", 404)
        if c["user_id"] != user["id"] and not has_perm(user, "order.comment.moderate"):
            return _err("Нет прав на редактирование", "forbidden", 403)
        text = (data.get("text") or "").strip()
        if not text:
            return _err("Пустой комментарий", "empty")
        con.execute(
            "UPDATE order_comments SET text=?, edited_at=? WHERE id=?", (text, iso(), comment_id)
        )
        con.commit()
        return jsonify({"comments": _comments(order_id)})
    finally:
        con.close()


@bp.delete("/api/orders/<int:order_id>/comments/<int:comment_id>")
@login_required
def delete_comment(order_id, comment_id):
    user = current_user()
    con = _open()
    try:
        c = con.execute(
            "SELECT * FROM order_comments WHERE id=? AND order_id=?",
            (comment_id, order_id),
        ).fetchone()
        if not c:
            return _err("Комментарий не найден", "not_found", 404)
        if c["user_id"] != user["id"] and not has_perm(user, "order.comment.moderate"):
            return _err("Нет прав на удаление", "forbidden", 403)
        con.execute("UPDATE order_comments SET deleted=1 WHERE id=?", (comment_id,))
        con.commit()
        return jsonify({"comments": _comments(order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/pause")
@login_required
def toggle_pause(order_id):
    user = current_user()
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        active = timetrack.pause_active(order_id)
        if active:
            timetrack.pause_end(con, order_id, user["id"])
        else:
            timetrack.pause_start(con, order_id, user["id"])
        con.commit()
        return jsonify({"time": timetrack.totals(order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/duplicate")
@permission_required("order.duplicate")
def duplicate(order_id):
    user = current_user()
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        new_order = oservice.duplicate_order(con, order, user)
        con.commit()
        audit("order_duplicate", "order", new_order["number"], f"from={order['number']}")
        return jsonify({"order": _full(con, new_order["id"])}), 201
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/archive")
@login_required
def archive(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.archive"):
        return _err("Forbidden: order.archive", "forbidden", 403)
    value = 1 if data.get("archive", True) else 0
    con = _open()
    try:
        con.execute(
            "UPDATE orders SET archive=?, updated_at=?, updated_by=?, version=version+1 "
            "WHERE id=?",
            (value, iso(), user["id"], order_id),
        )
        oservice.history_add(
            con, order_id, user["id"], "archive", "archive", None, value
        )
        con.commit()
        audit("order_archive", "order", order_id, str(value))
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.delete("/api/orders/<int:order_id>")
@permission_required("order.delete")
def soft_delete(order_id):
    user = current_user()
    con = _open()
    try:
        con.execute(
            "UPDATE orders SET deleted=1, deleted_at=?, deleted_by=?, version=version+1 "
            "WHERE id=?",
            (iso(), user["id"], order_id),
        )
        oservice.history_add(con, order_id, user["id"], "delete", "deleted", 0, 1)
        con.commit()
        audit("order_delete", "order", order_id)
        return jsonify({"ok": True})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/restore")
@permission_required("order.restore")
def restore(order_id):
    user = current_user()
    con = _open()
    try:
        con.execute(
            "UPDATE orders SET deleted=0, deleted_at=NULL, deleted_by=NULL, "
            "updated_at=?, updated_by=?, version=version+1 WHERE id=?",
            (iso(), user["id"], order_id),
        )
        oservice.history_add(con, order_id, user["id"], "restore", "deleted", 1, 0)
        con.commit()
        audit("order_restore", "order", order_id)
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.get("/api/orders/<int:order_id>/history")
@login_required
def order_history(order_id):
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        return jsonify(
            {
                "history": _history(order_id),
                "time": timetrack.totals(order_id),
                "vin_history": oservice.vin_history(con, order),
            }
        )
    finally:
        con.close()


@bp.put("/api/orders/<int:order_id>/parts")
@login_required
def parts_date(order_id):
    data = request.get_json(force=True, silent=True) or {}
    user = current_user()
    if not has_perm(user, "order.edit"):
        return _err("Forbidden: order.edit", "forbidden", 403)
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        con.execute(
            "UPDATE orders SET parts_expected_at=?, parts_attention=0, updated_at=?, "
            "updated_by=?, version=version+1 WHERE id=?",
            (data.get("expected_at"), iso(), user["id"], order_id),
        )
        oservice.history_add(
            con,
            order_id,
            user["id"],
            "parts_expected",
            "parts_expected_at",
            order.get("parts_expected_at"),
            data.get("expected_at"),
        )
        con.commit()
        return jsonify({"order": _full(con, order_id)})
    finally:
        con.close()


@bp.post("/api/orders/<int:order_id>/client-telegram/code")
@login_required
def client_code(order_id):
    import secrets

    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        code = secrets.token_hex(3).upper()
        existing = con.execute(
            "SELECT id FROM client_bindings WHERE order_id=? ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if existing:
            con.execute(
                "UPDATE client_bindings SET code=?, bound_at=NULL WHERE id=?",
                (code, existing["id"]),
            )
        else:
            con.execute(
                "INSERT INTO client_bindings(order_id, code, created_at) VALUES(?,?,?)",
                (order_id, code, iso()),
            )
        con.commit()
        from ..services import telegram

        link = telegram.start_link(code)
        return jsonify({"code": code, "link": link, "bot": telegram.bot_info()})
    finally:
        con.close()


@bp.get("/api/orders/<int:order_id>/vin-history")
@login_required
def vin_history(order_id):
    con = _open()
    try:
        order = oservice.get_order(con, order_id)
        if not order:
            return _err("Заказ не найден", "not_found", 404)
        return jsonify(oservice.vin_history(con, order))
    finally:
        con.close()


@bp.get("/api/orders/prefill")
@login_required
def prefill():
    source = request.args.get("from_order_id")
    template_id = request.args.get("template_id")
    out = {}
    if source:
        order = db.one("SELECT * FROM orders WHERE id=?", (int(source),))
        if order:
            out = {
                "plate": order["plate"],
                "vin": order["vin"],
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
                "source_order_id": order["id"],
            }
    elif template_id:
        tpl = db.one("SELECT * FROM card_templates WHERE id=?", (int(template_id),))
        if tpl:
            out = {
                "problem": tpl["problem"],
                "original_works": json.loads(tpl["original_works"] or "[]"),
                "work_type_ids": json.loads(tpl["work_type_ids"] or "[]"),
                "make": tpl["make"],
                "model": tpl["model"],
                "year": tpl["year"],
                "priority": tpl["priority"],
                "template_id": tpl["id"],
            }
    return jsonify({"prefill": out})
