import json, os

MAX_BYTES = 512 * 1024
STALE_S = 900
MAX_READINGS = 200
MAX_HOUSEKEEPING = 10
SILENT = "keeper silent"
STALE_REASON = "keeper file older than 15 minutes"
NAME_MAX = 64
VALUE_MAX = 64
REASON_MAX = 120
MADE_MAX = 40
CMD_MAX = 40
ENGINES = ("running", "down")


def path():
    return os.environ.get("FACTORY_KEEPER_FILE") or None


def missing(reason):
    return {"fileMadeAt": None, "fileAgeS": None, "fresh": False, "engine": "unknown", "skippedTicks": 0,
            "housekeeping": [], "readings": [{"name": "keeper_file", "value": None, "reason": reason, "source": "keeper"}]}


def value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v[:VALUE_MAX]
    return None


def reading(r, source, stale):
    if not isinstance(r, dict) or not isinstance(r.get("name"), str):
        return None
    reason = r.get("reason")
    if stale:
        return {"name": r["name"][:NAME_MAX], "value": None, "reason": STALE_REASON, "source": source}
    return {"name": r["name"][:NAME_MAX], "value": value(r.get("value")),
            "reason": reason[:REASON_MAX] if isinstance(reason, str) else None, "source": source}


def housekeeping(entries):
    out = []
    for h in entries if isinstance(entries, list) else []:
        if isinstance(h, dict) and isinstance(h.get("cmd"), str) and isinstance(h.get("rc"), int) \
                and isinstance(h.get("s"), int) and h["s"] >= 0:
            out.append({"cmd": h["cmd"][:CMD_MAX], "rc": h["rc"], "s": h["s"]})
    return out[:MAX_HOUSEKEEPING]


def read(now, p):
    try:
        with open(p, "rb") as f:
            st = os.fstat(f.fileno())
            if st.st_size > MAX_BYTES:
                return missing("keeper file over %d bytes" % MAX_BYTES)
            raw = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return missing("keeper file missing")
    except Exception as e:
        return missing("keeper file unreadable: %s" % type(e).__name__)
    if len(raw) > MAX_BYTES:
        return missing("keeper file over %d bytes" % MAX_BYTES)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        doc = None
    if not isinstance(doc, dict):
        return missing("keeper file is not an object")
    age = max(0, round(now - st.st_mtime))
    stale = age > STALE_S
    made = doc.get("madeAt")
    made = made if isinstance(made, str) and len(made) <= MADE_MAX else None
    factory = doc.get("factory") if isinstance(doc.get("factory"), dict) else {}
    rows = doc.get("readings") if isinstance(doc.get("readings"), list) else []
    rows = [reading(r, "keeper", stale) for r in rows]
    rows += [reading(r, "factory", stale) for r in (factory.get("readings") if isinstance(factory.get("readings"), list) else [])]
    skipped = doc.get("skippedTicks")
    return {"fileMadeAt": made, "fileAgeS": age, "fresh": not stale,
            "engine": "unknown" if stale or doc.get("engine") not in ENGINES else doc["engine"],
            "skippedTicks": skipped if isinstance(skipped, int) and not isinstance(skipped, bool) and skipped >= 0 else 0,
            "housekeeping": [] if stale else housekeeping(doc.get("housekeeping")),
            "readings": [r for r in rows if r is not None][:MAX_READINGS]}


def silent(m):
    if m["fresh"]:
        return None
    if m["fileAgeS"] is None:
        return "no keeper file: %s. The keeper timer on the host writes it every 5 minutes (deploy/vps/keeper.sh)." % m["readings"][0]["reason"]
    return ("keeper file is %d s old (made %s), over %d s: every keeper value shows as unknown. "
            "The keeper timer on the host writes it every 5 minutes (deploy/vps/keeper.sh).") % (m["fileAgeS"], m["fileMadeAt"] or "-", STALE_S)
