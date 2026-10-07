from .. import db
from ..timeutil import iso, now, parse


def _seconds(a, b) -> float:
    pa, pb = parse(a), parse(b) or now()
    if not pa:
        return 0.0
    return max(0.0, (pb - pa).total_seconds())


def close_intervals(con, order_id: int, at: str | None = None):
    con.execute(
        "UPDATE time_intervals SET ended_at=? WHERE order_id=? AND ended_at IS NULL",
        (at or iso(), order_id),
    )


def open_interval(con, order_id: int, status_id: int, at: str | None = None):
    close_intervals(con, order_id, at)
    con.execute(
        "INSERT INTO time_intervals(order_id, status_id, started_at) VALUES(?,?,?)",
        (order_id, status_id, at or iso()),
    )


def start_for_order(con, order_id: int, status_id: int, created_at: str):
    row = con.execute(
        "SELECT id FROM time_intervals WHERE order_id=? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    if row:
        cur = con.execute(
            "SELECT ended_at FROM time_intervals WHERE id=?", (row["id"],)
        ).fetchone()
        if cur and not cur["ended_at"]:
            return
    con.execute(
        "INSERT INTO time_intervals(order_id, status_id, started_at) VALUES(?,?,?)",
        (order_id, status_id, created_at),
    )


def pause_active(order_id: int) -> dict | None:
    return db.one(
        "SELECT * FROM pauses WHERE order_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
        (order_id,),
    )


def pause_start(con, order_id: int, user_id: int) -> dict | None:
    if pause_active(order_id):
        return None
    con.execute(
        "INSERT INTO pauses(order_id, user_id, started_at) VALUES(?,?,?)",
        (order_id, user_id, iso()),
    )
    con.execute(
        "INSERT INTO order_history(order_id, user_id, action, created_at) VALUES(?,?,?,?)",
        (order_id, user_id, "pause_start", iso()),
    )
    return pause_active(order_id)


def pause_end(con, order_id: int, user_id: int) -> dict | None:
    p = pause_active(order_id)
    if not p:
        return None
    con.execute(
        "UPDATE pauses SET ended_at=? WHERE id=?", (iso(), p["id"])
    )
    con.execute(
        "INSERT INTO order_history(order_id, user_id, action, created_at) VALUES(?,?,?,?)",
        (order_id, user_id, "pause_end", iso()),
    )
    return None


def totals(order_id: int) -> dict:
    order = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
    if not order:
        return {}
    intervals = db.query(
        "SELECT * FROM time_intervals WHERE order_id=? ORDER BY started_at", (order_id,)
    )
    statuses = {s["id"]: s for s in db.query("SELECT * FROM statuses")}
    t = now()
    stage_seconds = {}
    total = 0.0
    running_status = None
    for iv in intervals:
        sec = _seconds(iv["started_at"], iv["ended_at"])
        total += sec
        key = statuses.get(iv["status_id"], {}).get("key", str(iv["status_id"]))
        stage_seconds[key] = stage_seconds.get(key, 0) + sec
        if not iv["ended_at"]:
            running_status = key

    if not intervals and order.get("created_at"):
        total = _seconds(order["created_at"], None)

    pauses = db.query("SELECT * FROM pauses WHERE order_id=?", (order_id,))
    pause_seconds = sum(_seconds(p["started_at"], p["ended_at"]) for p in pauses)
    waiting_seconds = stage_seconds.get("parts", 0.0)
    working = max(0.0, total - waiting_seconds - pause_seconds)

    return {
        "total_seconds": round(total),
        "stage_seconds": {k: round(v) for k, v in stage_seconds.items()},
        "waiting_seconds": round(waiting_seconds),
        "pause_seconds": round(pause_seconds),
        "working_seconds": round(working),
        "running_status": running_status,
        "intervals": [
            {
                "id": iv["id"],
                "status_id": iv["status_id"],
                "status_key": statuses.get(iv["status_id"], {}).get("key"),
                "started_at": iv["started_at"],
                "ended_at": iv["ended_at"],
                "seconds": round(_seconds(iv["started_at"], iv["ended_at"])),
            }
            for iv in intervals
        ],
        "pauses": [
            {
                "id": p["id"],
                "user_id": p["user_id"],
                "started_at": p["started_at"],
                "ended_at": p["ended_at"],
                "seconds": round(_seconds(p["started_at"], p["ended_at"])),
            }
            for p in pauses
        ],
        "active_pause": pause_active(order_id) is not None,
    }
