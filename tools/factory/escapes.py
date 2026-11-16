import json
import re

import limits

WINDOW_S = 7 * 24 * 3600
EVERY = 10
LEDGER = "escaped"
DEV_RED = "dev red"

REPAIRS_LINE = re.compile(r"(?m)^[ \t]*\*\*Repairs\*\*:(.*)$")
NUMBER = re.compile(r"#(\d+)")
DEV_RED_JOB = re.compile(r"\(job #(\d+)\)")


def repairs(body):
    out = set()
    for line in REPAIRS_LINE.findall(str(body or "")):
        out.update(int(n) for n in NUMBER.findall(line))
    return sorted(out)


def in_window(at, now):
    return at is not None and 0 <= now - at <= WINDOW_S


def named_by(key, record):
    if key == DEV_RED:
        first = str(record.get("evidence") or "").split("\n")[0]
        return {int(n) for n in DEV_RED_JOB.findall(first)}
    return {int(n) for n in NUMBER.findall(key)}


def find(jobs, open_numbers, problems, now):
    repairers = {}
    for j in jobs:
        for n in repairs(j.get("body")):
            repairers.setdefault(n, set()).add(int(j["issue"]))
    problem_hits = {}
    for key, record in (problems or {}).items():
        for n in named_by(key, record):
            problem_hits.setdefault(n, set()).add("problem %s" % key)
    pairs = set()
    for j in jobs:
        if j["state"] != "merged" or not in_window(j.get("merged_at"), now):
            continue
        n = int(j["issue"])
        if open_numbers is not None and n in open_numbers:
            pairs.add((str(n), "reopened"))
        for m in repairers.get(n, ()):
            if m != n:
                pairs.add((str(n), "repair #%d" % m))
        for by in problem_hits.get(n, ()):
            pairs.add((str(n), by))
    return sorted(pairs)


def merged_at(store, job):
    rows = [t for t in store.transitions_of(str(job)) if t["to_state"] == "merged" and t["from_state"] != "merged"]
    return limits.ts(rows[-1]["at"]) if rows else None


def record(store, job, by, now):
    key = "%s|%s" % (job, by)
    if key in store.get_all(LEDGER):
        return False
    store.set(LEDGER, key, json.dumps({"job": str(job), "by": by, "at": now}))
    store.add_failure("escaped", str(job), reason=by)
    return True
