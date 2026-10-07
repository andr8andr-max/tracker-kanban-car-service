import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

from .. import config
from .. import db
from ..timeutil import iso, now
from ..security import audit


def create_backup(kind: str = "manual") -> dict:
    config.ensure_dirs()
    stamp = now().strftime("%Y%m%d-%H%M%S")
    filename = f"tracker-{kind}-{stamp}.db"
    path = os.path.join(config.BACKUP_DIR, filename)
    src = sqlite3.connect(config.DB_PATH, timeout=15)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    size = os.path.getsize(path)
    db.execute(
        "INSERT INTO backups(filename, created_at, size, kind) VALUES(?,?,?,?)",
        (filename, iso(), size, kind),
    )
    try:
        audit("backup_create", "backup", filename, kind)
    except Exception:
        pass
    prune()
    return {"filename": filename, "size": size, "kind": kind}


def list_backups() -> list[dict]:
    return db.query("SELECT * FROM backups ORDER BY id DESC")


def prune():
    keep = int(db.get_settings().get("backup_keep_days", 30))
    rows = db.query("SELECT * FROM backups ORDER BY id DESC")
    for row in rows[keep:]:
        path = os.path.join(config.BACKUP_DIR, row["filename"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        db.execute("DELETE FROM backups WHERE id=?", (row["id"],))
    cutoff = now() - timedelta(days=keep)
    for row in db.query("SELECT * FROM backups WHERE kind='daily'"):
        try:
            created = datetime.strptime(row["filename"], "tracker-daily-%Y%m%d-%H%M%S.db")
            created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                path = os.path.join(config.BACKUP_DIR, row["filename"])
                if os.path.exists(path):
                    os.remove(path)
                db.execute("DELETE FROM backups WHERE id=?", (row["id"],))
        except ValueError:
            continue


def restore_backup(backup_id: int, user=None) -> dict:
    row = db.one("SELECT * FROM backups WHERE id=?", (backup_id,))
    if not row:
        return {"ok": False, "error": "not_found"}
    path = os.path.join(config.BACKUP_DIR, row["filename"])
    if not os.path.exists(path):
        return {"ok": False, "error": "file_missing"}

    create_backup("emergency")

    src = sqlite3.connect(path, timeout=15)
    dst = sqlite3.connect(config.DB_PATH, timeout=15)
    try:
        dst.execute("PRAGMA foreign_keys=OFF")
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    db.invalidate_settings()
    audit("backup_restore", "backup", row["filename"], "restore")
    return {"ok": True, "filename": row["filename"]}


def backup_today_exists(kind: str = "daily") -> bool:
    today = now().strftime("%Y%m%d")
    return bool(
        db.one(
            "SELECT id FROM backups WHERE kind=? AND filename LIKE ? LIMIT 1",
            (kind, f"tracker-{kind}-{today}-%"),
        )
    )


def last_daily_time() -> str | None:
    row = db.one(
        "SELECT filename FROM backups WHERE kind='daily' ORDER BY id DESC LIMIT 1"
    )
    return row["filename"] if row else None
