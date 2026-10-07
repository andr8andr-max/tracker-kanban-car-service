# Проверка безопасности взаимодействия сотрудников. Запуск: python tests/security_test.py
import os
import sys
import tempfile

_TEST_DATA = os.path.join(tempfile.gettempdir(), "tracker_sec_data")
os.environ["TRACKER_DATA_DIR"] = _TEST_DATA

import shutil  # noqa: E402

if os.path.isdir(_TEST_DATA):
    shutil.rmtree(_TEST_DATA, ignore_errors=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker import create_app, db  # noqa: E402

app = create_app()
admin_c = app.test_client()
FAILED = []


def check(name, cond, info=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name} {info}")
    if not cond:
        FAILED.append(name)


def login_client(login, password):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"login": login, "password": password})
    return c, r


# --------------------------------------------------------------- unauth
anon = app.test_client()
for path in ("/api/board", "/api/orders/1", "/api/notifications",
             "/api/admin/users", "/api/admin/settings", "/api/stats"):
    check(f"anon 401 {path}", anon.get(path).status_code == 401)
check("anon 401 POST orders", anon.post("/api/orders", json={}).status_code == 401)

# --------------------------------------------------------------- CSRF / content-type
r = admin_c.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
check("login admin", r.status_code == 200)
check("form-encoded POST rejected (csrf)",
      admin_c.post("/api/auth/logout", data={"x": "1"}).status_code == 403)
r = admin_c.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
check("json login still ok", r.status_code == 200)

# --------------------------------------------------------------- test users
users = admin_c.get("/api/admin/users").get_json()["users"]
by_login = {u["login"]: u for u in users}


def make_user(login, role_key):
    role = db.one("SELECT id FROM roles WHERE key=?", (role_key,))
    r = admin_c.post("/api/admin/users", json={
        "login": login, "password": "initial1", "role_id": role["id"],
        "full_name": login,
    })
    assert r.status_code == 201, r.get_json()
    u = db.one("SELECT * FROM users WHERE login=?", (login,))
    c, lr = login_client(login, "initial1")
    assert lr.status_code == 200, lr.get_json()
    # снимаем must_change, чтобы поднять шлюз
    pr = c.post("/api/auth/password", json={"old_password": "initial1", "new_password": "SecPass1"})
    assert pr.status_code == 200, pr.get_json()
    return c


mech_c = make_user("sec_mech", "mechanic")
mgr_c = make_user("sec_mgr", "manager")

# --------------------------------------------------------------- RBAC: mechanic
for path in ("/api/admin/users", "/api/admin/roles", "/api/admin/settings",
             "/api/admin/statuses", "/api/admin/worktypes", "/api/admin/audit",
             "/api/admin/backups", "/api/admin/telegram", "/api/admin/orders",
             "/api/admin/checklist-templates", "/api/admin/card-templates"):
    check(f"mech 403 GET {path}", mech_c.get(path).status_code == 403)

order_id = db.one("SELECT id FROM orders WHERE deleted=0 ORDER BY id")["id"]
check("mech 403 create order", mech_c.post("/api/orders", json={"plate": "X111XX1"}).status_code == 403)
check("mech 403 move", mech_c.post(f"/api/orders/{order_id}/move", json={"status_id": 2}).status_code == 403)
check("mech 403 priority", mech_c.post(f"/api/orders/{order_id}/priority", json={"priority": "urgent"}).status_code == 403)
check("mech 403 assign", mech_c.post(f"/api/orders/{order_id}/responsible", json={"user_id": 1}).status_code == 403)
check("mech 403 archive", mech_c.post(f"/api/orders/{order_id}/archive", json={"archive": True}).status_code == 403)
check("mech 403 delete", mech_c.delete(f"/api/orders/{order_id}").status_code == 403)
check("mech 403 restore", mech_c.post(f"/api/orders/{order_id}/restore", json={}).status_code == 403)
check("mech 403 duplicate", mech_c.post(f"/api/orders/{order_id}/duplicate", json={}).status_code == 403)
check("mech 403 backup create", mech_c.post("/api/admin/backups", json={}).status_code == 403)
check("mech 403 role perms", mech_c.put("/api/admin/roles/1/permissions", json={"permissions": []}).status_code == 403)

r = mech_c.get("/api/stats")
check("mech stats view ok", r.status_code == 200)
check("mech stats not staff_view", r.get_json().get("staff_view") is False)
check("mech stats spoof user_id ignored",
      mech_c.get("/api/stats?user_id=1").get_json().get("staff_view") is False)
check("mech 403 stats export", mech_c.get("/api/stats/export").status_code == 403)

# профиль: подмена роли игнорируется
mech_before = mech_c.get("/api/me").get_json()["user"]
r = mech_c.put("/api/profile", json={"lang": "ru", "full_name": "Hacker", "role_id": 1})
check("profile role_id ignored", r.status_code == 200)
mech_after = mech_c.get("/api/me").get_json()["user"]
check("role unchanged", mech_after["role"]["key"] == mech_before["role"]["key"])

# --------------------------------------------------------------- RBAC: manager
check("mgr 403 GET admin users", mgr_c.get("/api/admin/users").status_code == 403)
check("mgr can move", mgr_c.post(f"/api/orders/{order_id}/move", json={"status_id": 1, "version": 1}).status_code in (200, 409))
check("mgr 403 priority (нет права)", mgr_c.post(f"/api/orders/{order_id}/priority", json={"priority": "urgent"}).status_code == 403)

# --------------------------------------------------------------- meta privacy
meta = mech_c.get("/api/meta").get_json()
leaks = [u for u in meta.get("users", []) if "telegram_chat_id" in u]
check("meta hides telegram_chat_id", not leaks, f"leaked={len(leaks)}")
adm_users = admin_c.get("/api/admin/users").get_json()["users"]
check("admin users keeps telegram field", any("telegram_chat_id" in u for u in adm_users))

# --------------------------------------------------------------- IDOR: notifications
db.execute(
    "INSERT INTO notifications(user_id, type, title, body, created_at) "
    "VALUES(?,?,?,?,?)",
    (db.one("SELECT id FROM users WHERE login='sec_mech'")["id"], "system",
     '{"ru":"t","en":"t"}', "", db.iso()),
)
nid = db.one("SELECT MAX(id) id FROM notifications")["id"]
admin_c.post("/api/notifications/read", json={"ids": [nid]})
row = db.one("SELECT read_at FROM notifications WHERE id=?", (nid,))
check("IDOR: чужое уведомление не прочитано", row["read_at"] is None)
mech_c.post("/api/notifications/read", json={"ids": [nid]})
row = db.one("SELECT read_at FROM notifications WHERE id=?", (nid,))
check("своё уведомление читается", row["read_at"] is not None)

# --------------------------------------------------------------- IDOR: comments
r = admin_c.post(f"/api/orders/{order_id}/comments", json={"text": "admin comment"})
check("admin comment added", r.status_code == 201, str(r.get_json())[:100])
cids = [c["id"] for c in r.get_json()["comments"]]
admin_cid = cids[-1]
r = mech_c.put(f"/api/orders/{order_id}/comments/{admin_cid}", json={"text": "deface"})
check("IDOR: чужой комментарий не редактируется", r.status_code == 403)
r = mech_c.post(f"/api/orders/{order_id}/comments", json={"text": "mech comment"})
mech_cid = [c["id"] for c in r.get_json()["comments"]][-1]
check("свой комментарий редактируется",
      mech_c.put(f"/api/orders/{order_id}/comments/{mech_cid}", json={"text": "mech edited"}).status_code == 200)
check("IDOR: чужой комментарий не удаляется",
      mech_c.delete(f"/api/orders/{order_id}/comments/{admin_cid}").status_code == 403)

# --------------------------------------------------------------- password gate
role = db.one("SELECT id FROM roles WHERE key='mechanic'")
admin_c.post("/api/admin/users", json={"login": "sec_gate", "password": "initial1",
                                        "role_id": role["id"], "full_name": "gate"})
g_c, r = login_client("sec_gate", "initial1")
check("gate user logged in", r.status_code == 200)
check("gate blocks api POST", g_c.post("/api/notifications/read", json={}).status_code == 403)
check("gate allows password change",
      g_c.post("/api/auth/password", json={"old_password": "initial1", "new_password": "SecPass1"}).status_code == 200)
check("gate lifted after change", g_c.post("/api/notifications/read", json={}).status_code == 200)

# --------------------------------------------------------------- session kill on password change
admin_c.post("/api/admin/users", json={"login": "sec_sess", "password": "initial1",
                                        "role_id": role["id"], "full_name": "sess"})
c1, r1 = login_client("sec_sess", "initial1")
c1.post("/api/auth/password", json={"old_password": "initial1", "new_password": "SecPass1"})
c2, r2 = login_client("sec_sess", "SecPass1")
check("second session ok", r2.status_code == 200)
r = c1.post("/api/auth/password", json={"old_password": "SecPass1", "new_password": "SecPass2"})
check("password change ok", r.status_code == 200)
check("other session killed", c2.get("/api/board").status_code == 401)
check("current session alive", c1.get("/api/board").status_code == 200)

# --------------------------------------------------------------- login brute-force
role_mech = role
admin_c.post("/api/admin/users", json={"login": "sec_victim", "password": "RightPass1",
                                        "role_id": role_mech["id"], "full_name": "v"})
codes = []
for i in range(11):
    r = app.test_client().post("/api/auth/login", json={"login": "sec_victim", "password": f"wrong{i}"})
    codes.append(r.status_code)
check("10 wrong passwords -> 401", all(c == 401 for c in codes[:10]), str(codes))
check("11th attempt -> 429", codes[10] == 429, str(codes[-1]))
r = app.test_client().post("/api/auth/login", json={"login": "sec_victim", "password": "RightPass1"})
check("correct password still blocked while throttled", r.status_code == 429)
r = app.test_client().post("/api/auth/login", json={"login": "admin", "password": "admin123"})
check("other logins unaffected by throttle", r.status_code == 200)

# --------------------------------------------------------------- recovery throttle
c4 = app.test_client()
rec_codes = []
for i in range(4):
    rec_codes.append(c4.post("/api/auth/recovery", json={"login": "admin"}).status_code)
check("recovery 4th request -> 429", rec_codes[3] == 429, str(rec_codes))

# brute-force recovery confirm -> code invalidated
db.execute("UPDATE users SET telegram_link_code='ABC123' WHERE login='sec_sess'")
cf_codes = []
for i in range(11):
    cf_codes.append(app.test_client().post(
        "/api/auth/recovery/confirm",
        json={"login": "sec_sess", "code": f"BAD{i:04d}", "new_password": "NewPass1"}).status_code)
check("confirm 1-8 -> 400", all(c == 400 for c in cf_codes[:8]), str(cf_codes[:8]))
check("confirm 11th -> 429", cf_codes[10] == 429, str(cf_codes))
row = db.one("SELECT telegram_link_code FROM users WHERE login='sec_sess'")
check("code invalidated after failed attempts", row["telegram_link_code"] is None)
r = app.test_client().post(
    "/api/auth/recovery/confirm",
    json={"login": "sec_sess", "code": "ABC123", "new_password": "NewPass1"})
check("original code no longer works", r.status_code in (400, 429), str(r.status_code))

# --------------------------------------------------------------- self-lockout guards
r = admin_c.put("/api/admin/users/1", json={"active": False})
check("admin cannot block self", r.status_code == 400, str(r.get_json()))
row = db.one("SELECT active FROM users WHERE login='admin'")
check("admin still active", bool(row["active"]))
check("admin cannot delete self",
      admin_c.delete("/api/admin/users/1").status_code == 400)

# --------------------------------------------------------------- logout with json ok
check("json logout ok", admin_c.post("/api/auth/logout", json={}).status_code == 200)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} -> {FAILED}")
    sys.exit(1)
print("ALL SECURITY CHECKS PASSED")
