"""Простейший скользящий rate-limit в памяти процесса.

Защита от перебора паролей/кодов восстановления и спам-запросов.
Счётчики сбрасываются при перезапуске сервера — осознанный компромисс
без изменения схемы БД; лимит и окно задаются на каждый вызов.
"""

import threading
import time

_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}


def _prune(key: str, window_sec: int) -> list[float]:
    now = time.time()
    ts = [t for t in _buckets.get(key, []) if now - t < window_sec]
    if ts:
        _buckets[key] = ts
    else:
        _buckets.pop(key, None)
    return ts


def blocked(key: str, limit: int, window_sec: int) -> bool:
    """True, если за окно уже накоплено limit попыток (ход заблокирован)."""
    with _lock:
        return len(_prune(key, window_sec)) >= limit


def hit(key: str, limit: int, window_sec: int) -> bool:
    """Фиксирует попытку; True, если этот hit превысил лимит."""
    with _lock:
        ts = _prune(key, window_sec)
        ts.append(time.time())
        _buckets[key] = ts
        return len(ts) > limit


def retry_after(key: str, window_sec: int) -> int:
    """Секунд до старта (грубая оценка: до истечения самого старого таймстампа)."""
    with _lock:
        ts = _prune(key, window_sec)
    if not ts:
        return 0
    return max(1, int(window_sec - (time.time() - ts[0])))


def reset(key: str):
    with _lock:
        _buckets.pop(key, None)
