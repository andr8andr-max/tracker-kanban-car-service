import os
import secrets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("TRACKER_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "tracker.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
SECRET_PATH = os.path.join(DATA_DIR, "secret.key")

DEFAULTS = {
    "service_name": "Автосервис",
    "default_lang": "ru",
    "org_tz_offset": 180,
    "session_timeout_min": 480,
    "session_secret": None,
    "telegram_token": "",
    "telegram_bot_login": "",
    "due_soon_hours": 24,
    "overdue_repeat_hours": 6,
    "ready_conditions": {"vin": True, "checklist": True, "responsible": True},
    "cancel_reasons": [
        {"key": "client_refused", "ru": "Клиент отказался", "en": "Client refused"},
        {"key": "no_parts", "ru": "Нет запчастей", "en": "Parts unavailable"},
        {"key": "duplicate", "ru": "Дублирование заказа", "en": "Duplicate order"},
        {"key": "other", "ru": "Другая причина", "en": "Other reason"},
    ],
    "auto_assign": {"enabled": False, "rule": "least_loaded"},
    "backup_keep_days": 30,
    "backup_time": "03:00",
    "notify_matrix": {},
    "overdue_notified_at": {},
    "due_notified_at": {},
}


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def secret_key() -> str:
    ensure_dirs()
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_PATH, "w", encoding="utf-8") as f:
        f.write(key)
    return key
