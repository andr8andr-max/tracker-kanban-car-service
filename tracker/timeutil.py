from datetime import datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    d = dt or now()
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    v = str(value).strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def org_offset_tz():
    from . import db

    minutes = int(db.get_settings().get("org_tz_offset", 180))
    return timezone(timedelta(minutes=minutes))


def org_now() -> datetime:
    return now().astimezone(org_offset_tz())


def hours_from_now(hours: float) -> str:
    return iso(now() + timedelta(hours=hours))


def norm_plate(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def norm_vin(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def norm_text(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


def fmt_ms(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"


def fmt_h(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}ч {m}м"
