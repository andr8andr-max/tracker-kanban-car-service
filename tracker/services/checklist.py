import json

from .. import db
from ..timeutil import iso, norm_text


def template_items(work_type_ids) -> list[dict]:
    ids = [int(x) for x in (work_type_ids or [])]
    if not ids:
        return []
    q = ",".join("?" for _ in ids)
    return db.query(
        f"SELECT t.*, w.position wp FROM checklist_templates t "
        f"JOIN work_types w ON w.id=t.work_type_id "
        f"WHERE t.work_type_id IN ({q}) ORDER BY wp, t.position, t.id",
        ids,
    )


def sync_checklist(con, order_id: int, work_type_ids, actor_id=None) -> dict:
    desired: dict[str, dict] = {}
    order_keys = []
    for tpl in template_items(work_type_ids):
        lang_text = tpl["text_ru"] or tpl["text_en"]
        key = norm_text(lang_text)
        if not key:
            continue
        if key not in desired:
            desired[key] = {
                "text": lang_text,
                "stage_key": tpl.get("stage_key") or "",
                "required": int(tpl.get("required") or 0),
                "wtypes": [],
            }
            order_keys.append(key)
        d = desired[key]
        d["wtypes"].append(int(tpl["work_type_id"]))
        d["required"] = max(d["required"], int(tpl.get("required") or 0))
        if not d["stage_key"]:
            d["stage_key"] = tpl.get("stage_key") or ""

    existing = con.execute(
        "SELECT * FROM order_checklist_items WHERE order_id=? ORDER BY position, id",
        (order_id,),
    ).fetchall()
    existing_map = {}
    for row in existing:
        item = dict(row)
        existing_map.setdefault(item["text_norm"], item)

    added = removed = merged = 0
    pos = 0
    for key in order_keys:
        d = desired[key]
        pos += 1
        wt = sorted(set(d["wtypes"]))
        if key in existing_map:
            item = existing_map[key]
            old_wt = set(json.loads(item["work_type_ids"] or "[]"))
            new_wt = sorted(old_wt | set(wt))
            if old_wt != set(wt):
                merged += 1
            con.execute(
                "UPDATE order_checklist_items SET work_type_ids=?, stage_key=? WHERE id=?",
                (json.dumps(new_wt), d["stage_key"] or item["stage_key"], item["id"]),
            )
        else:
            added += 1
            con.execute(
                "INSERT INTO order_checklist_items"
                "(order_id, text, text_norm, stage_key, required, done, work_type_ids, position) "
                "VALUES(?,?,?,?,?,0,?,?)",
                (
                    order_id,
                    d["text"],
                    key,
                    d["stage_key"],
                    d["required"],
                    json.dumps(wt),
                    pos,
                ),
            )

    for key, item in existing_map.items():
        if item["done"]:
            continue
        if not item["work_type_ids"] or item["work_type_ids"] == "[]":
            continue
        if key not in desired:
            removed += 1
            con.execute("DELETE FROM order_checklist_items WHERE id=?", (item["id"],))

    return {"added": added, "removed": removed, "merged": merged}


def items_for(order_id: int) -> list[dict]:
    rows = db.query(
        "SELECT * FROM order_checklist_items WHERE order_id=? ORDER BY position, id",
        (order_id,),
    )
    return rows


def progress(order_id: int) -> dict:
    rows = items_for(order_id)
    total = len(rows)
    done = sum(1 for r in rows if r["done"])
    req_total = sum(1 for r in rows if r["required"])
    req_done = sum(1 for r in rows if r["required"] and r["done"])
    return {
        "total": total,
        "done": done,
        "required_total": req_total,
        "required_done": req_done,
        "percent": int(done * 100 / total) if total else 0,
        "required_complete": req_total == req_done,
    }


def missing_required(order_id: int) -> list[dict]:
    rows = db.query(
        "SELECT id, text FROM order_checklist_items "
        "WHERE order_id=? AND required=1 AND done=0 ORDER BY position, id",
        (order_id,),
    )
    return rows


def set_done(con, item_id: int, user_id: int, done: bool):
    if done:
        con.execute(
            "UPDATE order_checklist_items SET done=1, done_by=?, done_at=? WHERE id=?",
            (user_id, iso(), item_id),
        )
    else:
        con.execute(
            "UPDATE order_checklist_items SET done=0, done_by=NULL, done_at=NULL WHERE id=?",
            (item_id,),
        )
