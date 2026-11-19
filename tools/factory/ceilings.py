import json

HOLD_S = 15 * 60
PREFIX = "ceiling:"


def cap(store, kind, now):
    raw = store.get_all("-").get(PREFIX + kind)
    if raw is None:
        return None
    try:
        got = json.loads(raw)
        n, until = got["cap"], got["until"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(n, int) or isinstance(n, bool) or not isinstance(until, (int, float)) or isinstance(until, bool):
        return None
    return n if until > now else None


def lower(store, kind, running, now):
    active = cap(store, kind, now)
    base = active if active is not None else running
    new = max(1, base // 2)
    store.set("-", PREFIX + kind, json.dumps({"cap": new, "until": now + HOLD_S}))
    return new, now + HOLD_S
