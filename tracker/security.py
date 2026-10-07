import functools

from flask import g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def verify_password(hashed: str, password: str) -> bool:
    if not hashed:
        return False
    try:
        return check_password_hash(hashed, password)
    except Exception:
        return False


def load_user() -> dict | None:
    token = session.get("token")
    if not token:
        return None
    row = db.one(
        "SELECT s.token, s.last_seen_at, s.created_at, u.* FROM sessions s "
        "JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,),
    )
    if not row:
        return None
    settings = db.get_settings()
    timeout_min = int(settings.get("session_timeout_min", 480))
    from .timeutil import now, parse

    last = parse(row["last_seen_at"])
    if last and (now() - last).total_seconds() > timeout_min * 60:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    if not row["active"]:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    db.execute(
        "UPDATE sessions SET last_seen_at=? WHERE token=?", (db.iso(), token)
    )
    return row


def current_user() -> dict | None:
    if "user" not in g:
        g.user = load_user()
    return g.user


def user_perms(user: dict | None) -> set[str]:
    if not user or not user.get("role_id"):
        return set()
    rows = db.query(
        "SELECT perm_key FROM role_permissions WHERE role_id=?", (user["role_id"],)
    )
    return {r["perm_key"] for r in rows}


def has_perm(user: dict | None, key: str) -> bool:
    if not user:
        return False
    perms = user_perms(user)
    return key in perms or "admin.*" in perms


GATE_ALLOWED = ("/api/auth/password", "/api/auth/logout")


def _password_gate(user: dict | None):
    if not user or not user.get("must_change_password"):
        return None
    if request.method == "GET" or not request.path.startswith("/api/"):
        return None
    if any(request.path.startswith(p) for p in GATE_ALLOWED):
        return None
    return (
        jsonify({"error": "password_required", "message": "Password change required"}),
        403,
    )


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "unauthorized", "message": "Unauthorized"}), 401
        gate = _password_gate(user)
        if gate:
            return gate
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def permission_required(key: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "unauthorized", "message": "Unauthorized"}), 401
            gate = _password_gate(user)
            if gate:
                return gate
            if not has_perm(user, key):
                return (
                    jsonify({"error": "forbidden", "message": "Forbidden: " + key}),
                    403,
                )
            g.user = user
            return fn(*args, **kwargs)

        return wrapper

    return deco


def audit(action: str, entity: str = "", entity_id="", detail="", user_id=None):
    uid = user_id
    if uid is None:
        u = current_user()
        uid = u["id"] if u else None
    db.execute(
        "INSERT INTO audit_log(user_id, action, entity, entity_id, ip, detail, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            uid,
            action,
            str(entity or ""),
            str(entity_id or ""),
            request.remote_addr if request else "",
            detail if isinstance(detail, str) else str(detail),
            db.iso(),
        ),
    )


def csrf_ok() -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    ct = (request.content_type or "").lower()
    if not ct:
        return True
    return "application/json" in ct
