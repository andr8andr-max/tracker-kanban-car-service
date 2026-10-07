import json

from . import db
from .security import hash_password
from .timeutil import iso, now, org_now
from datetime import timedelta

PERMISSIONS = [
    ("board.view", "Просмотр карточек", "View cards", "Доска", "Board"),
    ("order.create", "Создание заказа", "Create orders", "Заказы", "Orders"),
    ("order.edit", "Редактирование заказа", "Edit orders", "Заказы", "Orders"),
    ("order.move", "Перемещение между этапами", "Move between stages", "Заказы", "Orders"),
    ("order.priority", "Изменение приоритета", "Change priority", "Заказы", "Orders"),
    ("order.due", "Изменение срока", "Change due date", "Заказы", "Orders"),
    ("order.assign", "Назначение ответственного", "Assign responsible", "Заказы", "Orders"),
    ("order.worktypes", "Изменение типов работ", "Change work types", "Заказы", "Orders"),
    ("order.approve", "Согласование работ", "Approve works", "Заказы", "Orders"),
    ("order.comment", "Комментарии", "Comments", "Заказы", "Orders"),
    ("order.comment.moderate", "Модерация чек-листов", "Moderate checklists", "Заказы", "Orders"),
    ("order.checklist", "Работа с чек-листом", "Work with checklist", "Заказы", "Orders"),
    (
        "order.checklist.required",
        "Изменение обязательности пунктов",
        "Change item required flag",
        "Заказы",
        "Orders",
    ),
    ("order.duplicate", "Дублирование карточки", "Duplicate cards", "Заказы", "Orders"),
    ("order.archive", "Архивирование", "Archive", "Заказы", "Orders"),
    ("order.delete", "Удаление карточек", "Delete cards", "Заказы", "Orders"),
    ("order.restore", "Восстановление удалённых", "Restore deleted", "Заказы", "Orders"),
    ("stats.view", "Просмотр статистики", "View statistics", "Отчёты", "Reports"),
    ("stats.all", "Статистика по всем сотрудникам", "Statistics for all staff", "Отчёты", "Reports"),
    ("stats.export", "Экспорт статистики", "Export statistics", "Отчёты", "Reports"),
    ("users.manage", "Управление пользователями", "Manage users", "Администрирование", "Administration"),
    ("roles.manage", "Роли и права", "Roles and permissions", "Администрирование", "Administration"),
    ("board.manage", "Настройка Kanban", "Configure Kanban", "Администрирование", "Administration"),
    ("worktypes.manage", "Типы работ", "Work types", "Администрирование", "Administration"),
    ("templates.manage", "Шаблоны карточек", "Card templates", "Администрирование", "Administration"),
    ("checklists.manage", "Шаблоны чек-листов", "Checklist templates", "Администрирование", "Administration"),
    ("settings.manage", "Системные настройки", "System settings", "Администрирование", "Administration"),
    ("telegram.manage", "Настройка Telegram", "Telegram settings", "Администрирование", "Administration"),
    ("backup.manage", "Backup и восстановление", "Backup and restore", "Администрирование", "Administration"),
    ("audit.view", "История активности", "Activity log", "Администрирование", "Administration"),
]

ROLE_PERMS = {
    "mechanic": ["board.view", "order.edit", "order.comment", "order.checklist", "stats.view"],
    "diagnostics": ["board.view", "order.edit", "order.comment", "order.checklist", "stats.view"],
    "master": [
        "board.view", "order.create", "order.edit", "order.move", "order.priority",
        "order.due", "order.assign", "order.worktypes", "order.approve", "order.comment",
        "order.comment.moderate", "order.checklist", "order.checklist.required",
        "order.duplicate", "order.archive", "stats.view", "stats.all", "stats.export",
    ],
    "manager": [
        "board.view", "order.create", "order.edit", "order.move", "order.due",
        "order.assign", "order.worktypes", "order.approve", "order.comment",
        "order.checklist", "order.checklist.required", "order.duplicate",
        "order.archive", "stats.view", "stats.all", "stats.export",
    ],
    "admin": [p[0] for p in PERMISSIONS],
}

ROLES = [
    ("mechanic", "Механик", "Mechanic"),
    ("diagnostics", "Диагност", "Diagnostic"),
    ("master", "Мастер", "Master"),
    ("manager", "Менеджер", "Manager"),
    ("admin", "Администратор", "Administrator"),
]

STATUSES = [
    ("appointment", "Запись", "Appointment", "#0ea5e9"),
    ("intake", "Приём автомобиля", "Check-in", "#38bdf8"),
    ("diagnostics", "Диагностика", "Diagnostics", "#8b5cf6"),
    ("approval", "Согласование работ", "Work approval", "#f59e0b"),
    ("work", "В работе", "In progress", "#3b82f6"),
    ("parts", "Ожидание запчастей", "Waiting for parts", "#f97316"),
    ("ready", "Готово", "Ready", "#22c55e"),
    ("issued", "Выдано", "Issued", "#14b8a6"),
    ("cancelled", "Отменено", "Cancelled", "#ef4444"),
]

WORK_TYPES = [
    ("Диагностика", "Diagnostics", [
        ("Подключить сканер, считать коды ошибок", "Connect scanner, read error codes", "diagnostics", 1),
        ("Осмотреть автомобиль с подъёмника", "Inspect vehicle on lift", "diagnostics", 1),
        ("Проверить уровни жидкостей", "Check fluid levels", "diagnostics", 0),
    ]),
    ("ТО", "Maintenance", [
        ("Снять передние колёса", "Remove front wheels", "work", 1),
        ("Заменить моторное масло", "Replace engine oil", "work", 1),
        ("Заменить масляный фильтр", "Replace oil filter", "work", 1),
        ("Проверить тормозные колодки", "Check brake pads", "work", 0),
        ("Закрутить колёса с моментом", "Tighten wheels to torque", "work", 1),
    ]),
    ("Тормозная система", "Brake system", [
        ("Снять передние колёса", "Remove front wheels", "work", 1),
        ("Заменить тормозные колодки", "Replace brake pads", "work", 1),
        ("Проверить тормозную жидкость", "Check brake fluid", "work", 1),
        ("Прокачать тормоза", "Bleed brakes", "work", 0),
    ]),
    ("Подвеска", "Suspension", [
        ("Снять передние колёса", "Remove front wheels", "work", 1),
        ("Осмотреть сайлентблоки", "Inspect bushings", "diagnostics", 1),
        ("Заменить стойки стабилизатора", "Replace stabilizer links", "work", 0),
    ]),
    ("Ремонт двигателя", "Engine repair", [
        ("Слить масло", "Drain oil", "work", 1),
        ("Снять поддон", "Remove oil pan", "work", 1),
        ("Заменить прокладку", "Replace gasket", "work", 1),
    ]),
    ("Электрика", "Electrical", [
        ("Проверить аккумулятор", "Check battery", "diagnostics", 1),
        ("Считать коды ошибок", "Read error codes", "diagnostics", 1),
        ("Проверить генератор", "Check alternator", "diagnostics", 0),
    ]),
    ("Шиномонтаж", "Tire service", [
        ("Снять колёса", "Remove wheels", "work", 1),
        ("Балансировка колёс", "Wheel balancing", "work", 1),
        ("Проверить давление", "Check tire pressure", "work", 1),
    ]),
]


def seed_permissions_and_roles(con):
    for key, ru, en, gru, gen in PERMISSIONS:
        con.execute(
            "INSERT OR IGNORE INTO permissions(key, name_ru, name_en, grp_ru, grp_en) "
            "VALUES(?,?,?,?,?)",
            (key, ru, en, gru, gen),
        )
    for key, ru, en in ROLES:
        con.execute(
            "INSERT OR IGNORE INTO roles(key, name_ru, name_en, is_system) VALUES(?,?,?,1)",
            (key, ru, en),
        )
    for key, perms in ROLE_PERMS.items():
        role = con.execute("SELECT id FROM roles WHERE key=?", (key,)).fetchone()
        if not role:
            continue
        for p in perms:
            con.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id, perm_key) VALUES(?,?)",
                (role["id"], p),
            )


def seed_statuses(con):
    exists = con.execute("SELECT COUNT(*) c FROM statuses").fetchone()["c"]
    if exists:
        return
    for i, (key, ru, en, color) in enumerate(STATUSES, start=1):
        con.execute(
            "INSERT INTO statuses(key, name_ru, name_en, position, color, is_system) "
            "VALUES(?,?,?,?,?,1)",
            (key, ru, en, i, color),
        )


def seed_work_types(con):
    exists = con.execute("SELECT COUNT(*) c FROM work_types").fetchone()["c"]
    if exists:
        return
    for pos, (ru, en, items) in enumerate(WORK_TYPES, start=1):
        cur = con.execute(
            "INSERT INTO work_types(name_ru, name_en, position) VALUES(?,?,?)",
            (ru, en, pos),
        )
        for i, (tru, ten, stage, req) in enumerate(items, start=1):
            con.execute(
                "INSERT INTO checklist_templates(work_type_id, text_ru, text_en, stage_key, "
                "required, position) VALUES(?,?,?,?,?,?)",
                (cur.lastrowid, tru, ten, stage, req, i),
            )


def seed_settings(con):
    rows = con.execute("SELECT COUNT(*) c FROM settings").fetchone()["c"]
    cfg = dict(__import__("tracker.config", fromlist=["DEFAULTS"]).DEFAULTS)
    if not rows:
        for k, v in cfg.items():
            if v is None:
                continue
            con.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )
    else:
        for k, v in cfg.items():
            if v is None:
                continue
            con.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )
    reasons = cfg["cancel_reasons"] + [
        {"key": "approval_rejected", "ru": "Отказ в согласовании", "en": "Works not approved"},
    ]
    con.execute(
        "INSERT INTO settings(key, value) VALUES('cancel_reasons', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(reasons, ensure_ascii=False),),
    )
    con.execute(
        "INSERT INTO settings(key, value) VALUES('auto_assign', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (
            json.dumps(
                {
                    "enabled": True,
                    "rule": "least_loaded",
                    "status_roles": {
                        "diagnostics": "diagnostics",
                        "work": "mechanic",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )


def seed_users(con):
    exists = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    if exists:
        return
    users = [
        ("admin", "admin123", "admin", "Администратор системы", 0),
        ("master", "123456", "master", "Иванов Пётр", 1),
        ("manager", "123456", "manager", "Смирнова Ольга", 1),
        ("mechanic", "123456", "mechanic", "Кузнецов Алексей", 1),
        ("diag", "123456", "diagnostics", "Соколов Дмитрий", 1),
    ]
    for login, pwd, role_key, name, must_change in users:
        role = con.execute("SELECT id FROM roles WHERE key=?", (role_key,)).fetchone()
        con.execute(
            "INSERT INTO users(login, password_hash, must_change_password, role_id, "
            "full_name, lang, active, created_at) VALUES(?,?,?,?,?,'ru',1,?)",
            (login, hash_password(pwd), must_change, role["id"], name, iso()),
        )


def seed_demo(con):
    from .services import orders as order_service
    from .services import checklist as checklist_service

    if con.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]:
        return
    admin = dict(con.execute("SELECT * FROM users WHERE login='admin'").fetchone())
    manager = dict(con.execute("SELECT * FROM users WHERE login='manager'").fetchone())
    mechanic = dict(con.execute("SELECT * FROM users WHERE login='mechanic'").fetchone())
    diag = dict(con.execute("SELECT * FROM users WHERE login='diag'").fetchone())
    wt = {r["name_ru"]: r["id"] for r in con.execute("SELECT * FROM work_types").fetchall()}

    def mk(**kw):
        return order_service.create_order(con, kw, admin)

    def move(order, key, user=None):
        st = order_service.status_by_key(key)
        return order_service.move_order(
            con, order["id"], st["id"], user or admin, reason="client_refused"
        )

    t0 = org_now()

    o1 = mk(
        plate="А123АА77", vin="ZFA12345678901234", make="Lada", model="Vesta", year=2020,
        client_name="Петров Иван", client_phone="+7 900 111-22-33",
        problem="Скрип при торможении, вибрация руля",
        work_type_ids=[wt["Тормозная система"], wt["ТО"]],
        due_at=iso(now() + timedelta(days=2)),
    )
    move(o1, "intake")
    move(o1, "diagnostics")
    con.execute("UPDATE orders SET responsible_id=? WHERE id=?", (diag["id"], o1["id"]))
    items = checklist_service.items_for(o1["id"])
    for it in items[:3]:
        checklist_service.set_done(con, it["id"], diag["id"], True)
    con.execute(
        "INSERT INTO order_comments(order_id, user_id, text, created_at) VALUES(?,?,?,?)",
        (o1["id"], mechanic["id"], "Клиент просил подождать запчасти до среды.", iso()),
    )

    o2 = mk(
        plate="B777BO199", make="Toyota", model="Camry", year=2022,
        client_name="Сидорова Марина", client_phone="+7 903 444-55-66",
        problem="ТО-30000, замена масла и фильтров",
        work_type_ids=[wt["ТО"]],
        due_at=iso(now() + timedelta(hours=20)),
    )
    move(o2, "intake")
    move(o2, "diagnostics")
    move(o2, "approval")
    con.execute("UPDATE orders SET responsible_id=? WHERE id=?", (manager["id"], o2["id"]))

    o3 = mk(
        plate="К908ТН178", vin="JTDKB20U677654321", make="Toyota", model="Corolla", year=2018,
        client_name="Ким Алексей", client_phone="+7 999 777-88-99",
        problem="Не заводится утром, глохнет на ходу",
        work_type_ids=[wt["Электрика"]],
        due_at=iso(now() - timedelta(hours=5)),
        priority="critical",
    )
    move(o3, "intake")
    move(o3, "diagnostics")
    move(o3, "approval")
    move(o3, "work")
    move(o3, "parts")
    con.execute(
        "UPDATE orders SET responsible_id=?, parts_expected_at=? WHERE id=?",
        (mechanic["id"], iso(now() - timedelta(hours=2)), o3["id"]),
    )
    con.execute("UPDATE orders SET parts_attention=1 WHERE id=?", (o3["id"],))

    o4 = mk(
        plate="Е456РМ123", make="Kia", model="Rio", year=2019,
        client_name="Иванова Ольга", client_phone="+7 916 222-33-44",
        problem="Замена резины, балансировка",
        work_type_ids=[wt["Шиномонтаж"]],
        due_at=iso(now() + timedelta(days=1)),
    )
    move(o4, "intake")
    move(o4, "diagnostics")
    move(o4, "approval")
    move(o4, "work")
    move(o4, "ready")
    con.execute("UPDATE orders SET responsible_id=? WHERE id=?", (mechanic["id"], o4["id"]))

    o5 = mk(
        plate="О222СС54", make="Hyundai", model="Solaris", year=2021,
        client_name="Гаврилов Роман", client_phone="+7 926 555-66-77",
        problem="Диагностика подвески после ямы",
        work_type_ids=[wt["Подвеска"]],
        due_at=iso(now() + timedelta(days=4)),
        priority="urgent",
    )
    move(o5, "intake")
    move(o5, "diagnostics")
    con.execute("UPDATE orders SET responsible_id=? WHERE id=?", (diag["id"], o5["id"]))

    o6 = mk(
        plate="Т010ТМ999", make="VW", model="Polo", year=2017,
        client_name="Морозов Кирилл", client_phone="+7 985 000-11-22",
        problem="Клиент передумал, отменил запись",
        work_type_ids=[],
    )
    move(o6, "intake")
    move(o6, "diagnostics")
    move(o6, "cancelled")

    con.commit()


def seed_demo_history(con):
    from .services import orders as order_service

    if con.execute("SELECT COUNT(*) c FROM orders WHERE vin IS NOT NULL AND vin<>''").fetchone()["c"] > 1:
        return
    admin = dict(con.execute("SELECT * FROM users WHERE login='admin'").fetchone())
    old = order_service.create_order(
        con,
        {
            "plate": "А123АА77",
            "vin": "ZFA12345678901234",
            "make": "Lada",
            "model": "Vesta",
            "year": 2020,
            "client_name": "Петров Иван",
            "client_phone": "+7 900 111-22-33",
            "problem": "Плановое ТО, замена колодок",
            "work_type_ids": [],
        },
        admin,
    )
    for key in ("intake", "diagnostics", "approval", "work", "ready", "issued"):
        order_service.status_by_key(key)
        st = order_service.status_by_key(key)
        order_service.move_order(
            con, old["id"], st["id"], admin, reason="client_refused", allow_ready_override=True
        )
    con.commit()


def _seed_due_maps(con):
    """Отмечаем сроки демо-заказов как уже напоминанные, чтобы планировщик
    не рассылал пачку «Просрочка/Приближение срока» при первом старте."""
    from .timeutil import parse

    t = iso()
    overdue, due = {}, {}
    rows = con.execute(
        "SELECT id, due_at FROM orders WHERE due_at IS NOT NULL AND deleted=0"
    ).fetchall()
    now_ts = now()
    for r in rows:
        d = parse(r["due_at"])
        if not d:
            continue
        if d < now_ts:
            overdue[str(r["id"])] = t
        elif (d - now_ts).total_seconds() <= 24 * 3600:
            due[str(r["id"])] = t
    for key, value in (("overdue_notified_at", overdue), ("due_notified_at", due)):
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def run_seed(demo: bool = True):
    db.init_db()
    con = db.connect()
    try:
        seed_permissions_and_roles(con)
        seed_statuses(con)
        seed_work_types(con)
        seed_settings(con)
        seed_users(con)
        con.commit()
        if demo:
            fresh = con.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] == 0
            from .services import notify as notify_service

            with notify_service.quiet():
                seed_demo(con)
                seed_demo_history(con)
            if fresh:
                _seed_due_maps(con)
        con.commit()
    finally:
        con.close()
    db.invalidate_settings()
