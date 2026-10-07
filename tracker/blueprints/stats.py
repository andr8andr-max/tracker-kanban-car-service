import csv
import io
import json

from flask import Blueprint, Blueprint, jsonify, request, Response

from .. import db
from ..security import current_user, has_perm, login_required, permission_required
from ..services import orders as oservice, timetrack
from ..timeutil import fmt_h, now, org_offset_tz, parse

bp = Blueprint("stats", __name__)

TERMINAL_KEYS = ("issued", "ready", "cancelled")


def _filters(user):
    args = {
        "from": request.args.get("from") or "",
        "to": request.args.get("to") or "",
        "user_id": request.args.get("user_id") or "",
        "status_key": request.args.get("status_key") or "",
        "work_type": request.args.get("work_type") or "",
        "group": request.args.get("group") or "day",
    }
    if not has_perm(user, "stats.all"):
        args["user_id"] = str(user["id"])
    return args


def _period_where(args, alias="o"):
    where = [f"{alias}.deleted=0"]
    sql_args = []
    if args["from"]:
        where.append(f"{alias}.created_at>=?")
        sql_args.append(args["from"])
    if args["to"]:
        where.append(f"{alias}.created_at<=?")
        sql_args.append(args["to"])
    if args["user_id"]:
        where.append(
            f"({alias}.responsible_id=? OR {alias}.created_by=?)"
        )
        sql_args += [int(args["user_id"]), int(args["user_id"])]
    if args["status_key"]:
        where.append("s.key=?")
        sql_args.append(args["status_key"])
    if args["work_type"]:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(o.work_type_ids) je WHERE je.value=?)"
        )
        sql_args.append(int(args["work_type"]))
    return " AND ".join(where), sql_args


def compute_stats(args: dict) -> dict:
    where, sql_args = _period_where(args)
    orders = db.query(
        "SELECT o.*, s.key status_key FROM orders o JOIN statuses s ON s.id=o.status_id "
        f"WHERE {where}",
        sql_args,
    )
    order_ids = [o["id"] for o in orders]
    statuses = {s["key"]: s for s in db.query("SELECT * FROM statuses")}
    users = {
        str(u["id"]): (u["full_name"] or u["login"])
        for u in db.query("SELECT id, full_name, login FROM users")
    }

    completed = [o for o in orders if o["status_key"] == "issued"]
    active = [o for o in orders if o["status_key"] not in TERMINAL_KEYS]
    overdue = [
        o
        for o in orders
        if o.get("due_at")
        and parse(o["due_at"])
        and parse(o["due_at"]) < now()
        and o["status_key"] not in ("issued", "cancelled")
    ]

    intervals = []
    if order_ids:
        q = ",".join("?" for _ in order_ids)
        intervals = db.query(
            f"SELECT * FROM time_intervals WHERE order_id IN ({q})", order_ids
        )
    status_map = {s["id"]: s["key"] for s in db.query("SELECT id, key FROM statuses")}

    intake_to_ready = []
    for o in orders:
        iv = [i for i in intervals if i["order_id"] == o["id"]]
        start = next((i for i in iv if status_map.get(i["status_id"]) == "intake"), None)
        end = next((i for i in iv if status_map.get(i["status_id"]) == "ready"), None)
        if start and end and parse(end["started_at"]) and parse(start["started_at"]):
            intake_to_ready.append(
                (parse(end["started_at"]) - parse(start["started_at"])).total_seconds()
            )

    stage_seconds = {}
    stage_counts = {}
    waiting_seconds = 0.0
    for i in intervals:
        key = status_map.get(i["status_id"], "?")
        sec = timetrack._seconds(i["started_at"], i["ended_at"])
        stage_seconds[key] = stage_seconds.get(key, 0) + sec
        stage_counts[key] = stage_counts.get(key, 0) + 1
        if key == "parts":
            waiting_seconds += sec

    avg_stage = {
        k: int(stage_seconds[k] / stage_counts[k])
        for k in stage_seconds
        if stage_counts.get(k)
    }

    load = {}
    for o in active:
        if o["responsible_id"]:
            load[users.get(str(o["responsible_id"]), str(o["responsible_id"]))] = (
                load.get(users.get(str(o["responsible_id"]), str(o["responsible_id"])), 0) + 1
            )

    by_employee = {}
    for o in orders:
        name = users.get(str(o["responsible_id"]), "—") if o["responsible_id"] else "—"
        by_employee[name] = by_employee.get(name, 0) + 1

    by_work_type = {}
    wt_names = {str(w["id"]): w["name_ru"] for w in db.query("SELECT * FROM work_types")}
    for o in orders:
        for wid in json.loads(o["work_type_ids"] or "[]"):
            name = wt_names.get(str(wid), str(wid))
            by_work_type[name] = by_work_type.get(name, 0) + 1

    dynamics = {}
    tz = org_offset_tz()
    group = args.get("group") or "day"
    for o in completed:
        d = parse(o["updated_at"]) or parse(o["created_at"])
        local = d.astimezone(tz) if d else None
        if not local:
            continue
        if group == "month":
            label = local.strftime("%Y-%m")
        elif group == "week":
            label = local.strftime("%Y-W%W")
        else:
            label = local.strftime("%Y-%m-%d")
        dynamics[label] = dynamics.get(label, 0) + 1

    avg_ready = int(sum(intake_to_ready) / len(intake_to_ready)) if intake_to_ready else 0

    return {
        "period": {"from": args.get("from"), "to": args.get("to")},
        "total_orders": len(orders),
        "completed": len(completed),
        "active": len(active),
        "overdue": len(overdue),
        "avg_intake_to_ready_seconds": avg_ready,
        "avg_intake_to_ready": fmt_h(avg_ready),
        "avg_stage_seconds": avg_stage,
        "avg_stage": {k: fmt_h(v) for k, v in avg_stage.items()},
        "waiting_seconds": int(waiting_seconds),
        "waiting": fmt_h(waiting_seconds),
        "load_by_employee": load,
        "orders_by_employee": by_employee,
        "by_work_type": by_work_type,
        "dynamics": [{"label": k, "count": v} for k, v in sorted(dynamics.items())],
        "overdue_orders": [
            {"id": o["id"], "number": o["number"], "plate": o["plate"], "due_at": o["due_at"]}
            for o in overdue
        ],
        "active_orders": len(active),
        "staff_view": has_perm(current_user(), "stats.all"),
    }


def _detail_rows(args):
    where, sql_args = _period_where(args)
    rows = db.query(
        "SELECT o.*, s.key status_key, s.name_ru status_name, u.full_name resp_name, u.login resp_login "
        "FROM orders o JOIN statuses s ON s.id=o.status_id "
        "LEFT JOIN users u ON u.id=o.responsible_id "
        f"WHERE {where} ORDER BY o.created_at DESC",
        sql_args,
    )
    out = []
    for o in rows:
        t = timetrack.totals(o["id"])
        out.append(
            {
                "number": o["number"],
                "created_at": o["created_at"],
                "plate": o["plate"],
                "vin": o["vin"],
                "car": f"{o['make']} {o['model']}".strip(),
                "client": o["client_name"],
                "phone": o["client_phone"],
                "status": o["status_name"],
                "responsible": (o["resp_name"] or o["resp_login"]) if o["responsible_id"] else "",
                "priority": o["priority"],
                "due_at": o["due_at"] or "",
                "work_types": ", ".join(
                    w["name_ru"]
                    for w in db.query(
                        "SELECT * FROM work_types WHERE id IN "
                        f"({','.join('?' for _ in json.loads(o['work_type_ids'] or '[]')) or 'NULL'})",
                        json.loads(o["work_type_ids"] or "[]"),
                    )
                ),
                "total": fmt_h(t.get("total_seconds", 0)),
                "working": fmt_h(t.get("working_seconds", 0)),
                "waiting": fmt_h(t.get("waiting_seconds", 0)),
                "overdue": "да" if (o["due_at"] and parse(o["due_at"]) and parse(o["due_at"]) < now() and o["status_key"] not in ("issued", "cancelled")) else "",
            }
        )
    return out


@bp.get("/api/stats")
@permission_required("stats.view")
def stats():
    user = current_user()
    args = _filters(user)
    return jsonify(compute_stats(args))


@bp.get("/api/stats/export")
@permission_required("stats.export")
def export():
    user = current_user()
    args = _filters(user)
    fmt = (request.args.get("format") or "csv").lower()
    summary = compute_stats(args)
    rows = _detail_rows(args)

    headers = [
        ("number", "Заказ"), ("created_at", "Создан"), ("plate", "Госномер"),
        ("vin", "VIN"), ("car", "Автомобиль"), ("client", "Клиент"),
        ("phone", "Телефон"), ("status", "Статус"), ("responsible", "Ответственный"),
        ("priority", "Приоритет"), ("due_at", "Срок"), ("work_types", "Типы работ"),
        ("total", "Общее время"), ("working", "Рабочее время"),
        ("waiting", "Ожидание запчастей"), ("overdue", "Просрочка"),
    ]

    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Заказы"
        ws.append([h[1] for h in headers])
        for r in rows:
            ws.append([r.get(k) or "" for k, _ in headers])
        ws2 = wb.create_sheet("Сводка")
        ws2.append(["Показатель", "Значение"])
        ws2.append(["Период с", args.get("from") or "—"])
        ws2.append(["Период по", args.get("to") or "—"])
        ws2.append(["Всего заказов", summary["total_orders"]])
        ws2.append(["Завершено", summary["completed"]])
        ws2.append(["В работе", summary["active"]])
        ws2.append(["Просрочено", summary["overdue"]])
        ws2.append(["Среднее время приём→готово", summary["avg_intake_to_ready"]])
        ws2.append(["Ожидание запчастей", summary["waiting"]])
        for k, v in (summary["orders_by_employee"] or {}).items():
            ws2.append([f"Заказов: {k}", v])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=stats-{args.get('from') or 'all'}.xlsx"
            },
        )

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Сводка"])
    writer.writerow(["Период с", args.get("from") or "—"])
    writer.writerow(["Период по", args.get("to") or "—"])
    writer.writerow(["Всего заказов", summary["total_orders"]])
    writer.writerow(["Завершено", summary["completed"]])
    writer.writerow(["В работе", summary["active"]])
    writer.writerow(["Просрочено", summary["overdue"]])
    writer.writerow(["Среднее время приём→готово", summary["avg_intake_to_ready"]])
    writer.writerow([])
    writer.writerow([h[1] for h in headers])
    for r in rows:
        writer.writerow([r.get(k) or "" for k, _ in headers])
    data = buf.getvalue().encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=stats-{args.get('from') or 'all'}.csv"
        },
    )
