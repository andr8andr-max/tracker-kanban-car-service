import json
import sqlite3

from . import config
from .timeutil import iso, norm_plate, norm_text, norm_vin, now, parse  # noqa: F401

_SETTINGS_CACHE: dict | None = None


def invalidate_settings():
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None


def get_settings() -> dict:
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        cfg = dict(config.DEFAULTS)
        rows = query("SELECT key, value FROM settings")
        for r in rows:
            try:
                cfg[r["key"]] = json.loads(r["value"])
            except Exception:
                cfg[r["key"]] = r["value"]
        _SETTINGS_CACHE = cfg
    return _SETTINGS_CACHE


def set_setting(key: str, value):
    cfg = get_settings()
    cfg[key] = value
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    invalidate_settings()


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def query(sql: str, args=()) -> list[dict]:
    con = connect()
    try:
        cur = con.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def one(sql: str, args=()) -> dict | None:
    con = connect()
    try:
        cur = con.execute(sql, args)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def execute(sql: str, args=()) -> int:
    con = connect()
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid or cur.rowcount
    finally:
        con.close()


def executescript(script: str):
    con = connect()
    try:
        con.executescript(script)
        con.commit()
    finally:
        con.close()


def tx():
    return connect()


SCHEMA = """
CREATE TABLE IF NOT EXISTS roles(
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  name_ru TEXT NOT NULL,
  name_en TEXT NOT NULL,
  is_system INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS permissions(
  key TEXT PRIMARY KEY,
  name_ru TEXT NOT NULL,
  name_en TEXT NOT NULL,
  grp_ru TEXT NOT NULL,
  grp_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_permissions(
  role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  perm_key TEXT NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,
  PRIMARY KEY(role_id, perm_key)
);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  login TEXT UNIQUE NOT NULL,
  password_hash TEXT,
  must_change_password INTEGER DEFAULT 0,
  role_id INTEGER REFERENCES roles(id),
  full_name TEXT DEFAULT '',
  lang TEXT DEFAULT 'ru',
  lang_custom INTEGER NOT NULL DEFAULT 0,
  telegram_chat_id TEXT,
  telegram_linked_at TEXT,
  telegram_link_code TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  last_login_at TEXT,
  failed_logins INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS statuses(
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  name_ru TEXT NOT NULL,
  name_en TEXT NOT NULL,
  position INTEGER NOT NULL,
  color TEXT DEFAULT '#64748b',
  is_system INTEGER DEFAULT 1,
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS work_types(
  id INTEGER PRIMARY KEY,
  name_ru TEXT NOT NULL,
  name_en TEXT NOT NULL,
  position INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS checklist_templates(
  id INTEGER PRIMARY KEY,
  work_type_id INTEGER NOT NULL REFERENCES work_types(id) ON DELETE CASCADE,
  text_ru TEXT NOT NULL,
  text_en TEXT DEFAULT '',
  stage_key TEXT DEFAULT '',
  required INTEGER DEFAULT 1,
  position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS card_templates(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  problem TEXT DEFAULT '',
  original_works TEXT DEFAULT '[]',
  work_type_ids TEXT DEFAULT '[]',
  make TEXT DEFAULT '',
  model TEXT DEFAULT '',
  year INTEGER,
  priority TEXT DEFAULT 'normal',
  active INTEGER DEFAULT 1,
  position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY,
  vin TEXT,
  make TEXT DEFAULT '',
  model TEXT DEFAULT '',
  year INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicle_plates(
  id INTEGER PRIMARY KEY,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
  plate_raw TEXT NOT NULL,
  plate_norm TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  order_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_plates_norm ON vehicle_plates(plate_norm);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY,
  number TEXT UNIQUE NOT NULL,
  status_id INTEGER NOT NULL REFERENCES statuses(id),
  position REAL DEFAULT 0,
  vehicle_id INTEGER REFERENCES vehicles(id),
  vin TEXT DEFAULT '',
  plate TEXT DEFAULT '',
  plate_norm TEXT DEFAULT '',
  make TEXT DEFAULT '',
  model TEXT DEFAULT '',
  year INTEGER,
  client_name TEXT DEFAULT '',
  client_phone TEXT DEFAULT '',
  client_telegram TEXT DEFAULT '',
  problem TEXT DEFAULT '',
  original_works TEXT DEFAULT '[]',
  approved_works TEXT DEFAULT '[]',
  work_type_ids TEXT DEFAULT '[]',
  responsible_id INTEGER REFERENCES users(id),
  priority TEXT DEFAULT 'normal',
  due_at TEXT,
  approval_state TEXT,
  approval_started_at TEXT,
  cancel_reason TEXT,
  cancel_at TEXT,
  cancel_by INTEGER,
  parts_expected_at TEXT,
  parts_attention INTEGER DEFAULT 0,
  archive INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0,
  deleted_at TEXT,
  deleted_by INTEGER,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT,
  updated_by INTEGER,
  version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_orders_vin ON orders(vin);
CREATE INDEX IF NOT EXISTS idx_orders_plate ON orders(plate_norm);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status_id, deleted, archive);
CREATE TABLE IF NOT EXISTS order_stage_executors(
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  status_id INTEGER NOT NULL REFERENCES statuses(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY(order_id, status_id)
);
CREATE TABLE IF NOT EXISTS order_checklist_items(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  text_norm TEXT NOT NULL,
  stage_key TEXT DEFAULT '',
  required INTEGER DEFAULT 1,
  done INTEGER DEFAULT 0,
  done_by INTEGER,
  done_at TEXT,
  work_type_ids TEXT DEFAULT '[]',
  position INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_checklist_order ON order_checklist_items(order_id);
CREATE TABLE IF NOT EXISTS order_comments(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  deleted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS order_history(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  user_id INTEGER,
  action TEXT NOT NULL,
  field TEXT,
  old_value TEXT,
  new_value TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_order ON order_history(order_id);
CREATE TABLE IF NOT EXISTS time_intervals(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  status_id INTEGER NOT NULL REFERENCES statuses(id),
  started_at TEXT NOT NULL,
  ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_time_order ON time_intervals(order_id);
CREATE TABLE IF NOT EXISTS pauses(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  user_id INTEGER,
  started_at TEXT NOT NULL,
  ended_at TEXT
);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  order_id INTEGER,
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  link TEXT DEFAULT '',
  read_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, read_at);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id TEXT,
  ip TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backups(
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  created_at TEXT NOT NULL,
  size INTEGER DEFAULT 0,
  kind TEXT DEFAULT 'daily'
);
CREATE TABLE IF NOT EXISTS counters(
  year INTEGER PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS client_bindings(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  telegram_chat_id TEXT,
  bound_at TEXT,
  created_at TEXT NOT NULL
);
"""


def effective_lang(user) -> str:
    """Язык пользователя: собственный выбор (lang_custom) или язык по умолчанию."""
    if user and user.get("lang_custom") and user.get("lang") in ("ru", "en"):
        return user["lang"]
    d = get_settings().get("default_lang")
    return d if d in ("ru", "en") else "ru"


def init_db():
    config.ensure_dirs()
    executescript(SCHEMA)
    _migrate()


def _migrate():
    cols = [r["name"] for r in query("PRAGMA table_info(users)")]
    if "lang_custom" not in cols:
        execute("ALTER TABLE users ADD COLUMN lang_custom INTEGER NOT NULL DEFAULT 0")
