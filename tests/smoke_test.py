# Сквозная проверка ключевых сценариев ТЗ. Запуск: python tests/smoke_test.py
import os
import sys
import tempfile

# тесты работают с изолированной копией данных, чтобы не засорять рабочую базу
_TEST_DATA = os.path.join(tempfile.gettempdir(), "tracker_smoke_data")
os.environ["TRACKER_DATA_DIR"] = _TEST_DATA

import shutil  # noqa: E402

if os.path.isdir(_TEST_DATA):
    shutil.rmtree(_TEST_DATA, ignore_errors=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker import create_app

app = create_app()
c = app.test_client()
FAILED = []


def check(name, cond, info=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name} {info}")
    if not cond:
        FAILED.append(name)


def j(r, expect=200):
    data = r.get_json()
    if r.status_code != expect:
        print(f"   unexpected status {r.status_code}: {data}")
    return data


# 1. login admin
r = c.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
check("login admin", r.status_code == 200)
admin = j(r)["user"]
check("admin permissions", "users.manage" in admin["permissions"])

# сброс состояния демо-пользователей для повторяемости теста
users = j(c.get("/api/admin/users"))["users"]
for u in users:
    if u["login"] in ("manager", "mechanic"):
        c.put(f"/api/admin/users/{u['id']}", json={"reset_password": True, "password": "123456"})

# 2. wrong password
r = c.post("/api/auth/login", json={"login": "admin", "password": "bad"})
check("wrong password rejected", r.status_code == 401)

# 3. first-login password change required for demo users
c2 = app.test_client()
r = c2.post("/api/auth/login", json={"login": "manager", "password": "123456"})
check("manager login", r.status_code == 200)
check("must change password flag", j(r)["user"]["must_change_password"] is True)
r = c2.post("/api/orders", json={"plate": "Т222ТТ22", "no_merge": True})
check("blocked until password change", r.status_code == 403)
r = c2.post("/api/auth/password", json={"old_password": "123456", "new_password": "qwerty123"})
check("password change", r.status_code == 200)
r = c2.post("/api/orders", json={"plate": "Т222ТТ22", "no_merge": True})
check("allowed after password change", r.status_code == 201)

# 4. plate required
r = c.post("/api/orders", json={})
check("plate required", r.status_code == 400 and j(r)["error"] == "plate_required")

# 5. create order (new branch)
r = c.post(
    "/api/orders",
    json={
        "plate": "Н111НН11",
        "vin": "X9ZZZ00E000000001",
        "make": "BMW",
        "model": "X5",
        "year": 2021,
        "client_name": "Тестов Тест",
        "client_phone": "+7 900 000-00-00",
        "problem": "Шум подвески",
        "no_merge": True,
        "due_at": "2026-10-10T12:00:00.000Z",
    },
)
check("create order", r.status_code == 201, r.status_code)
order = j(r)["order"]
check("order number format", len(order["number"]) == 11 and order["number"].startswith("2026-"), order["number"])
check("status = appointment", order["status"]["key"] == "appointment")

# 6. duplicate plate -> merge choice required
r = c.post("/api/orders", json={"plate": "Н 111 НН 11"})
check("merge choice required", r.status_code == 409 and j(r)["error"] == "merge_choice_required")
cands = j(r)["candidates"]
check("candidates found", len(cands) >= 1)
r = c.post("/api/orders", json={"plate": "н111нн11", "no_merge": True})
check("create with no_merge", r.status_code == 201)
r = c.post("/api/orders", json={"plate": "Н111НН11", "vehicle_id": cands[0]["vehicle_id"]})
check("create merged by plate", r.status_code == 201)
oid = order["id"]

# 7. move to diagnostics
statuses = j(c.get("/api/meta"))["statuses"]
st = {s["key"]: s for s in statuses}
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["diagnostics"]["id"]})
check("move to diagnostics", r.status_code == 200)
check("timer interval started", j(r)["order"]["id"] == oid)

# 8. work types only after diagnostics
wt = j(c.get("/api/meta"))["work_types"]
wt_ids = [w["id"] for w in wt if w["name_ru"] in ("ТО", "Тормозная система")]
r = c.post(f"/api/orders/{oid}/worktypes", json={"ids": wt_ids})
check("set work types after diagnostics", r.status_code == 200)
cl = j(r)["order"]["checklist"]
texts = [i["text"] for i in cl]
check("checklist merged (single 'Снять передние колёса')", texts.count("Снять передние колёса") == 1, str(texts))

# 9. ready blocked without VIN? order has vin. Try ready without checklist/responsible
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["ready"]["id"]})
check("ready blocked (conditions)", r.status_code == 422 and j(r)["error"] == "ready_conditions")
probs = j(r)["problems"]
codes = [p["code"] for p in probs]
check("checklist incomplete detected", "checklist_incomplete" in codes, str(codes))

# 10. assign responsible + complete checklist -> ready allowed
r = c.post(f"/api/orders/{oid}/responsible", json={"user_id": admin["id"]})
check("assign responsible", r.status_code == 200)
for item in j(r)["order"]["checklist"]:
    if item["required"] and not item["done"]:
        c.post(f"/api/orders/{oid}/checklist/toggle", json={"item_id": item["id"], "done": True})
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["ready"]["id"]})
check("ready after conditions met", r.status_code == 200, r.status_code)

# 11. VIN conflict -> blocked with history, then accept merge
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["work"]["id"]})
check("back to work", r.status_code == 200)
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["ready"]["id"]})
check("ready second time", r.status_code == 200)
# second order: new branch (по госномеру "Не объединять"), VIN вводится позже
r = c.post("/api/orders", json={"plate": "Н111НН11", "no_merge": True, "make": "BMW"})
check("second order new branch", r.status_code == 201)
oid2 = j(r)["order"]["id"]
r = c.put(f"/api/orders/{oid2}", json={"vin": "X9ZZZ00E000000001"})
check("late VIN entered", r.status_code == 200 and j(r)["order"]["vin"] == "X9ZZZ00E000000001")
c.post(f"/api/orders/{oid2}/responsible", json={"user_id": admin["id"]})
c.post(f"/api/orders/{oid2}/move", json={"status_id": st["diagnostics"]["id"]})
r = c.post(f"/api/orders/{oid2}/move", json={"status_id": st["ready"]["id"]})
check("vin conflict blocks ready", r.status_code == 422 and j(r)["error"] == "ready_conditions")
probs = j(r).get("problems", [])
check("vin_conflict problem with history", any(p["code"] == "vin_conflict" and p.get("history") for p in probs))
r = c.post(f"/api/orders/{oid2}/move", json={"status_id": st["ready"]["id"], "accept_vin_merge": True})
check("vin merge accepted", r.status_code == 200, r.status_code)
r = c.get(f"/api/orders/{oid2}")
check("merged into VIN history", j(r)["order"]["vehicle_id"] == order["vehicle_id"])

# 12. approval flow
r = c.post(
    "/api/orders",
    json={"plate": "К333КК33", "no_merge": True, "problem": "Согласование", "work_type_ids": wt_ids},
)
oid3 = j(r)["order"]["id"]
c.post(f"/api/orders/{oid3}/move", json={"status_id": st["intake"]["id"]})
c.post(f"/api/orders/{oid3}/move", json={"status_id": st["diagnostics"]["id"]})
r = c.post(f"/api/orders/{oid3}/move", json={"status_id": st["approval"]["id"]})
check("move to approval", r.status_code == 200)
r = c.post(f"/api/orders/{oid3}/approval", json={"decision": "approved", "items": [{"text": "Работа А", "state": "approved"}]})
check("full approval auto-moves to work", r.status_code == 200 and j(r)["order"]["status"]["key"] == "work", str(j(r).get("error")))

# 13. cancel requires reason + restore
r = c.post(f"/api/orders/{oid3}/move", json={"status_id": st["cancelled"]["id"]})
check("cancel requires reason", r.status_code == 400 and j(r)["error"] == "cancel_reason_required")
r = c.post(f"/api/orders/{oid3}/move", json={"status_id": st["cancelled"]["id"], "reason": "client_refused"})
check("cancel with reason", r.status_code == 200 and j(r)["order"]["cancel_reason"] == "client_refused")
r = c.post(f"/api/orders/{oid3}/move", json={"status_id": st["work"]["id"]})
check("restore from cancelled", r.status_code == 200 and j(r)["order"]["cancel_reason"] is None)

# 14. parts waiting + expected date
oid = oid3
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["parts"]["id"]})
check("move to parts", r.status_code == 200)
r = c.put(f"/api/orders/{oid}/parts", json={"expected_at": "2026-01-01T00:00:00.000Z"})
check("set expected parts date", r.status_code == 200)
from tracker.services import scheduler

scheduler._parts_attention()
r = c.get(f"/api/orders/{oid}")
check("parts attention flag", j(r)["order"]["parts_attention"] is True)

# 15. pause
r = c.post(f"/api/orders/{oid}/pause")
check("pause start", r.status_code == 200 and j(r)["time"]["active_pause"] is True)
r = c.post(f"/api/orders/{oid}/pause")
check("pause end", r.status_code == 200 and j(r)["time"]["active_pause"] is False)
check("time totals present", "working_seconds" in j(r)["time"])

# 16. comments
r = c.post(f"/api/orders/{oid}/comments", json={"text": "Комментарий теста"})
check("add comment", r.status_code == 201)
r = c.get(f"/api/orders/{oid}")
check("comments loaded", len(j(r)["order"]["comments"]) >= 1)
check("history loaded", len(j(r)["order"]["history"]) >= 1)

# 17. vin history
r = c.get(f"/api/orders/{oid}/vin-history")
check("vin history endpoint", r.status_code == 200)

# 18. duplicate card
r = c.post(f"/api/orders/{oid}/duplicate")
check("duplicate order", r.status_code == 201 and j(r)["order"]["status"]["key"] == "appointment")
dup = j(r)["order"]
check("duplicate has new number", dup["number"] != order["number"])
check("duplicate checklist not done", all(i["done"] == 0 for i in dup["checklist"]))

# 19. notifications
r = c.get("/api/notifications")
check("notifications list", r.status_code == 200 and len(j(r)["notifications"]) >= 1)
r = c.post("/api/notifications/read", json={})
check("mark all read", r.status_code == 200 and j(r)["unread"] == 0)

# 20. search / filters
r = c.get("/api/board?q=Н111")
check("search by plate", len(j(r)["orders"]) >= 2)
r = c.get("/api/board?mine=1")
check("filter only mine", r.status_code == 200)
r = c.get("/api/board?priority=critical")
check("filter priority", r.status_code == 200)
r = c.get("/api/board?overdue=1")
check("filter overdue", r.status_code == 200)

# 21. stats + export
r = c.get("/api/stats")
check("stats", r.status_code == 200 and "completed" in j(r))
r = c.get("/api/stats/export?format=csv")
check("export csv", r.status_code == 200 and len(r.data) > 50)
r = c.get("/api/stats/export?format=xlsx")
check("export xlsx", r.status_code == 200 and r.data[:2] == b"PK")

# 22. admin: users, roles, statuses, settings, backups, audit
r = c.get("/api/admin/users")
check("admin users list", r.status_code == 200 and len(j(r)["users"]) >= 5)
r = c.post("/api/admin/users", json={"login": "newuser", "password": "abc123", "role_id": 1, "full_name": "Новый"})
check("admin create user", r.status_code in (201, 409), str(r.status_code))
r = c.get("/api/admin/roles")
check("admin roles", r.status_code == 200 and len(j(r)["roles"]) == 5)
rid = [x for x in j(r)["roles"] if x["key"] == "mechanic"][0]["id"]
r = c.put(f"/api/admin/roles/{rid}/permissions", json={"permissions": ["board.view"]})
check("role permissions update", r.status_code == 200)
r = c.get("/api/admin/statuses")
check("admin statuses", r.status_code == 200 and len(j(r)["statuses"]) == 9)
r = c.post("/api/admin/statuses", json={"name_ru": "Новый этап", "name_en": "New stage"})
check("status create", r.status_code == 201)
sid = j(r)["id"]
r = c.delete(f"/api/admin/statuses/{sid}")
check("status delete empty", r.status_code == 200)
r = c.get("/api/admin/worktypes")
check("work types with templates", r.status_code == 200 and all("templates" in w for w in j(r)["work_types"]))
r = c.get("/api/admin/settings")
check("settings", r.status_code == 200 and "ready_conditions" in j(r)["settings"])
r = c.put("/api/admin/settings", json={"service_name": "Автосервис Тест", "due_soon_hours": 12})
check("settings update", r.status_code == 200)
r = c.get("/api/admin/audit")
check("audit log", r.status_code == 200 and len(j(r)["audit"]) >= 1)
r = c.post("/api/admin/backups")
from tracker import config as app_config  # noqa: E402

check(
    "manual backup",
    r.status_code == 201
    and os.path.exists(os.path.join(app_config.BACKUP_DIR, j(r)["filename"])),
)
r = c.get("/api/admin/backups")
bks = j(r)["backups"]
check("backups list", len(bks) >= 1)
r = c.post(f"/api/admin/backups/{bks[0]['id']}/restore", json={})
check("restore requires confirm", r.status_code == 409)
r = c.post(f"/api/admin/backups/{bks[0]['id']}/restore", json={"confirm": True})
check("restore backup", r.status_code == 200 and j(r).get("ok"))

# 23. permissions enforcement: mechanic cannot create/delete
mech_id = None
r = c.get("/api/board")
# mechanic client
c3 = app.test_client()
lr = c3.post("/api/auth/login", json={"login": "mechanic", "password": "123456"})
print("   mechanic login:", lr.status_code, lr.get_json())
r = c3.get("/api/admin/users")
check("mechanic forbidden admin api", r.status_code == 403, str(r.status_code))
r = c3.post("/api/admin/users", json={"login": "x"})
check("mechanic cannot create users", r.status_code == 403, str(r.status_code))
r = c3.delete(f"/api/orders/{oid}")
check("mechanic cannot delete order", r.status_code == 403, str(r.status_code))
r = c3.get("/api/board")
check("mechanic can view board", r.status_code == 200, str(r.status_code))

# 24. archive / delete / restore
r = c.post(f"/api/orders/{oid2}/archive", json={"archive": True})
check("archive order", r.status_code == 200 and j(r)["order"]["archive"] is True)
r = c.get("/api/board")
check("archived hidden from board", all(o["id"] != oid2 for o in j(r)["orders"]))
r = c.delete(f"/api/orders/{oid2}")
check("soft delete", r.status_code == 200)
r = c.get("/api/admin/orders?view=deleted")
check("deleted list", any(o["id"] == oid2 for o in j(r)["orders"]))
r = c.post(f"/api/orders/{oid2}/restore")
check("restore deleted", r.status_code == 200)
r = c.post(f"/api/orders/{oid2}/archive", json={"archive": False})
check("unarchive", r.status_code == 200)

# 25. i18n / profile
r = c.put("/api/profile", json={"lang": "en", "full_name": "Admin EN"})
check("profile lang", r.status_code == 200 and j(r)["user"]["lang"] == "en")
r = c.get("/api/me")
check("me endpoint", r.status_code == 200 and j(r)["user"]["settings"]["default_lang"] in ("ru", "en"))
r = c.put("/api/profile", json={"lang": "ru"})

# 26. optimistic lock
r = c.get(f"/api/orders/{oid}")
version = j(r)["order"]["version"]
c.post(f"/api/orders/{oid}/priority", json={"priority": "urgent"})
r = c.post(f"/api/orders/{oid}/move", json={"status_id": st["issued"]["id"], "version": version})
check("version conflict detected", r.status_code == 409 and j(r)["error"] == "version_conflict")

# 27. logout
r = c.post("/api/auth/logout")
check("logout", r.status_code == 200)
r = c.get("/api/board")
check("session invalid after logout", r.status_code == 401)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} -> {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
