import datetime
import json

import clocks
import cutshape
import digest
import pools
import states
import store as ledger_store
import waits

RUNNING = states.RUNNING
END = states.END
WAIT_STATES = states.WAIT_STATES
TYPES = ("coder", "reviewer", "researcher", "designer")
MAX_JOBS = 200
MAX_EPICS = 50
MAX_READS = 5
KINDS = ("feature", "review_fix", "fix", "upgrade", "refactor", "research", "other")
DEPARTMENTS = (
    ("docs/research", "design"), ("supabase", "database"), ("apps/engine", "engine"),
    ("apps/ui/app/api", "backend"), ("packages/contracts", "backend"),
    ("apps/ui", "frontend"), ("packages/ui", "frontend"), ("packages/i18n", "frontend"),
    ("tools/factory", "tooling"), (".github", "tooling"), ("deploy", "tooling"), ("docs", "docs"),
)
MAX_BYTES = 200 * 1024
DIGEST_BYTES = 16 * 1024
EPICS_BYTES = 6 * 1024
PLANNING_BYTES = 8 * 1024
SMALL_BYTES = 4 * 1024
TITLE_MAX = 120
REASON_MAX = 200
HISTORY_MAX = 10
RUNS_MAX = 6
SHORT_MAX = 40
REPOS_MAX = 50
READY_LINES_MAX = 10
WHY_MAX = 120
PROBES_MAX = 5
ORDER_LIST_MAX = 50
ENABLED_MAX = 50
STATIONS_MAX = 20
MINIMAL = ("version", "madeAt", "beat", "repo", "jobs", "holds", "pools", "endedToday", "control")
MAX_PLANS = 5
MAX_RUNS = 8


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cut(text, n):
    return None if text is None else str(text)[:n]


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def _entered(store, j):
    rows = store.transitions_of(str(j["issue"]))
    changed = [r for r in rows if r["from_state"] != r["to_state"]]
    if changed:
        return changed[-1]["at"]
    return rows[0]["at"] if rows else (j.get("updated_at") or ledger_store.now())


def _reason(j):
    state = j["state"]
    if state in END:
        text = j.get("reason")
    elif state == "waiting" and j.get("file_wait"):
        text = "waits for #%d, same file %s" % tuple(j["file_wait"])
    elif state == "waiting":
        text = j.get("wait_line") or ("waits on " + ", ".join("#%d" % d for d in j["waiting"]) if j.get("waiting") else j.get("wait_reason"))
    elif state in WAIT_STATES:
        text = j.get("wait_reason")
    else:
        text = None
    return _cut(text or None, REASON_MAX)


def _department(paths):
    count = {}
    for p in paths:
        for prefix, dept in DEPARTMENTS:
            if p == prefix or p.startswith(prefix + "/"):
                count[dept] = count.get(dept, 0) + 1
                break
    order = []
    for _, dept in DEPARTMENTS:
        if dept in count and dept not in order:
            order.append(dept)
    if not order:
        return None, []
    main = max(order, key=lambda d: (count[d], -order.index(d)))
    return main, [d for d in order if d != main]


def _kind(title, labels):
    for lab in labels or []:
        name = str((lab or {}).get("name") or "").lower().replace("-", "_")
        if name in KINDS:
            return name
    t = str(title or "").lower()
    if "review" in t and "fix" in t:
        return "review_fix"
    for word in ("fix", "upgrade", "refactor", "research", "feature"):
        if word in t:
            return word
    return "other"


def _epic(store, n, read_epic, budget):
    row = store.db.execute("SELECT v FROM kv WHERE job='-' AND k=?", ("epic:%d" % n,)).fetchone()
    if row:
        try:
            c = json.loads(row[0])
            return str(c["title"])[:256], c["kind"]
        except (ValueError, KeyError, TypeError):
            pass
    if read_epic is not None and budget[0] > 0:
        budget[0] -= 1
        try:
            r = read_epic(n)
            title = str(r["title"])[:256]
            kind = _kind(title, r.get("labels"))
            store.set("-", "epic:%d" % n, json.dumps({"title": title, "kind": kind}))
            return title, kind
        except Exception:  # noqa: BLE001 - an unreadable epic keeps its number
            pass
    return "#%d" % n, "other"


def _epics(store, kept, read_epic):
    live, rest = set(), set()
    for j in kept:
        p = cutshape.parse({"number": j["issue"], "body": j.get("body") or ""}).get("parent")
        if p is not None:
            (live if j["state"] not in END else rest).add(p)
    chosen = (sorted(live, reverse=True) + sorted(rest - live, reverse=True))[:MAX_EPICS]
    budget = [MAX_READS]
    out = []
    for n in sorted(chosen):
        title, kind = _epic(store, n, read_epic, budget)
        out.append({"issue": n, "title": title, "kind": kind})
    return out


def _job(store, cfg, names, j, completed):
    running = j["state"] in RUNNING
    parsed = cutshape.parse({"number": j["issue"], "body": j.get("body") or ""})
    waiting_on = None
    if j["state"] == "waiting":
        previous = waits.dependency_numbers(j)
        waiting_on = [n for n in previous if n not in completed and store.get_all(str(n)).get("close_reason") != "completed"]
        if waiting_on != previous:
            j = waits.keep_dependencies(j, waiting_on)
        if not j.get("wait_line") and not waiting_on and not j.get("file_wait") and j.get("wait_reason") == "dependency":
            j = dict(j, wait_reason=None)
    steps = None
    if running and j.get("fire_id") is not None:
        row = store.db.execute("SELECT steps FROM fires WHERE id=?", (j["fire_id"],)).fetchone()
        steps = row[0] if row else None
    rnd = j.get("round")
    history = [{"state": states.APP_STATE.get(r["to_state"], r["to_state"]), "at": r["at"], "reason": _cut(r["reason"], REASON_MAX), "runId": _cut(r["run_id"], 64)}
               for r in store.transitions_of(str(j["issue"])) if r["from_state"] != r["to_state"]][-HISTORY_MAX:]
    ids = {n: i for i, n in names.items()}
    rows = store.db.execute("SELECT stage, coworker, status, intent_at, ended_at, tokens_in, tokens_out, run_id, cache_read "
                            "FROM fires WHERE job=? ORDER BY id", (str(j["issue"]),)).fetchall()[-RUNS_MAX:]
    runs = [{"stage": _cut(r[0], 20), "coworkerId": ids.get(r[1]) or _cut(r[1], 64), "status": _cut(r[2], 20),
             "startedAt": r[3], "endedAt": r[4], "tokensIn": int(r[5] or 0), "tokensOut": int(r[6] or 0),
             "runId": _cut(r[7], 64), **({"cacheRead": int(r[8])} if r[8] is not None else {})} for r in rows]
    main, others = _department(parsed.get("paths") or [])
    job = {
        "issue": j["issue"], "title": str(j.get("title") or "")[:TITLE_MAX], "state": states.APP_STATE.get(j["state"], j["state"]),
        "enteredAt": _entered(store, j), "pr": j.get("pr"),
        "round": rnd if isinstance(rnd, int) and 1 <= rnd <= 9 else None,
        "coworker": names.get(j.get("agent")) if running else None,
        "copy": j.get("copy") if running else None,
        "steps": steps, "tokensIn": None, "tokensOut": None,
        "parent": parsed.get("parent"), "dependsOn": list(parsed.get("deps") or [])[:20],
        "reason": _reason(j), "history": history, "runs": runs,
    }
    if waiting_on is not None:
        job["waitingOn"] = waiting_on[:20]
    if "closed_seen" in store.get_all(str(j["issue"])):
        job["closedOutside"] = True
    if main:
        job["department"] = main
        if others:
            job["departments"] = others
    return job


def _plan(p):
    runs = [{"id": str(c["id"])[:64], "name": str(c["name"])[:64], "runId": str(c["runId"])[:64], "startedAt": c["startedAt"],
             "steps": None if c.get("steps") is None else max(0, int(c["steps"]))} for c in p["coworkers"][:MAX_RUNS]]
    return {"parent": None if p["parent"] is None else int(p["parent"]), "title": str(p["title"])[:256], "coworkers": runs,
            "children": max(0, int(p["children"])), "filed": max(0, int(p["filed"]))}


def size(v):
    return len(json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _shrink_list(items, room, oldest_first=True):
    while items and size(items) > room:
        items.pop(0 if oldest_first else -1)
    return items


def _sections(snap):
    d = snap.get("digest")
    if isinstance(d, dict) and size(d) > DIGEST_BYTES:
        d.pop("machine", None)
        if size(d) > DIGEST_BYTES:
            del snap["digest"]
    if "epics" in snap:
        _shrink_list(snap["epics"], EPICS_BYTES)
    if "planning" in snap:
        _shrink_list(snap["planning"], PLANNING_BYTES - size(snap.get("plan")), oldest_first=False)
        if size([snap["planning"], snap.get("plan")]) > PLANNING_BYTES:
            snap.pop("plan", None)
    elif size(snap.get("plan")) > PLANNING_BYTES:
        snap.pop("plan", None)
    small = lambda: size([snap.get("machine"), snap.get("runStats"), snap["pools"], snap["holds"]])
    m = snap.get("machine")
    if isinstance(m, dict) and small() > SMALL_BYTES:
        m = snap["machine"] = dict(m, readings=list(m.get("readings") or []))
    while isinstance(m, dict) and m.get("readings") and small() > SMALL_BYTES:
        m["readings"].pop()
    if isinstance(m, dict) and small() > SMALL_BYTES:
        del snap["machine"]


def _lists(snap):
    p = snap.get("projects")
    if isinstance(p, dict):
        p["repos"] = list(p.get("repos") or [])[:REPOS_MAX]
    w = snap.get("work_order")
    if isinstance(w, dict):
        for k in ("issues", "done", "skipped"):
            w[k] = list(w.get(k) or [])[:ORDER_LIST_MAX]
    pr = snap.get("providers")
    if isinstance(pr, dict):
        pr["enabled"] = list(pr.get("enabled") or [])[:ENABLED_MAX]
    t = snap.get("throttle")
    if isinstance(t, dict) and isinstance(t.get("stations"), dict):
        t["stations"] = dict(sorted(t["stations"].items())[:STATIONS_MAX])


def _ready(snap, lines, probes):
    p = snap.get("projects")
    if not isinstance(p, dict):
        return
    p["probes"] = list(p.get("probes") or [])[-probes:]
    p["ready"] = [dict(r, lines=[dict(x, why=str(x.get("why") or "")[:WHY_MAX]) for x in (r.get("lines") or [])[:lines]])
                  for r in p.get("ready") or []]


def _drop_ready(snap):
    p = snap.get("projects")
    if not isinstance(p, dict):
        return
    keep = {snap.get("repo"), snap.get("home")}
    for r in sorted([r for r in p["ready"] if r.get("repo") not in keep], key=lambda r: str(r.get("at") or "")):
        if not _over(snap):
            return
        p["ready"] = [x for x in p["ready"] if x is not r]


class _Jobs:
    def __init__(self, snap):
        self.snap, self.rest = snap, size(dict(snap, jobs=[])) - 2
        self.cost = {id(j): size(j) for j in snap["jobs"]}
        self.jobs = size(snap["jobs"])

    def over(self):
        return self.rest + self.jobs > MAX_BYTES

    def empty(self, j):
        j["history"], j["runs"] = [], []
        new = size(j)
        self.jobs += new - self.cost[id(j)]
        self.cost[id(j)] = new

    def drop(self, j):
        self.snap["jobs"] = [k for k in self.snap["jobs"] if k is not j]
        self.jobs -= self.cost.pop(id(j)) + 1


def _over(snap):
    return size(snap) > MAX_BYTES


def fit(snap):
    if not _over(snap):
        return snap
    _sections(snap)
    t = _Jobs(snap)
    order = sorted(snap["jobs"], key=lambda j: (j["state"] not in END, j["enteredAt"]))
    for j in order:
        if not t.over():
            break
        t.empty(j)
    for j in [j for j in order if j["state"] in END]:
        if not t.over():
            break
        t.drop(j)
    if not _over(snap):
        return snap
    for j in snap["jobs"]:
        j["title"], j["reason"] = j["title"][:SHORT_MAX], _cut(j["reason"], SHORT_MAX)
    for step in (_lists, lambda s: _ready(s, READY_LINES_MAX, PROBES_MAX), lambda s: _ready(s, 1, 1), _drop_ready):
        if not _over(snap):
            return snap
        step(snap)
    if not _over(snap):
        return snap
    small = {k: snap[k] for k in MINIMAL if k in snap}
    small["jobs"] = [j for j in snap["jobs"] if j["state"] not in END]
    t = _Jobs(small)
    for j in sorted(small["jobs"], key=lambda j: j["enteredAt"]):
        if not t.over():
            break
        t.drop(j)
    while small["jobs"] and _over(small):
        small["jobs"].pop(0)
    return small


def _system_error(status, error):
    return status == "error" and clocks.klass("ERROR", {"error": (error or "").split(" ended ", 1)[-1]}) in ("transient", "plan_limit")


def _run_stats(store, now):
    since = iso(now - 86400)
    rows = [r for r in store.db.execute("SELECT status, seconds, error FROM fires WHERE status IN ('done','error') AND ended_at >= ?",
                                        (since,)).fetchall() if not _system_error(r[0], r[2])]
    took = [r[1] for r in rows if r[1] is not None]
    return {"since": since, "finished": len(rows), "errors": sum(1 for r in rows if r[0] == "error"),
            "avgRunS": round(sum(took) / len(took), 1) if took else None}


def build_snapshot(store, cfg, now, holds_active, beat=0, read_epic=None, planning=None, plan=None, machine=None):
    names = pools.names(cfg)
    all_jobs = store.jobs()
    completed = {j["issue"] for j in all_jobs if j["state"] in ("merged", "superseded")}
    live = [j for j in all_jobs if j["state"] not in END]
    ended = sorted((j for j in all_jobs if j["state"] in END), key=lambda j: str(j.get("updated_at") or ""), reverse=True)
    kept = sorted((live + ended)[:MAX_JOBS], key=lambda j: int(j["issue"]))
    out = {}
    for j in all_jobs:
        if j["state"] in RUNNING and j.get("agent"):
            out[j["agent"]] = out.get(j["agent"], 0) + 1
    pool_list = []
    for t, v in pools.types(cfg).items():
        if t in TYPES and len(pool_list) < 8:
            pool_list.append({"type": t, "coworkers": [
                {"name": c["name"][:64], "id": c["id"][:64], "runs": _clamp(pools.copies(cfg, c), 1, 32), "out": _clamp(out.get(c["id"], 0), 0, 32)}
                for c in v["coworkers"][:20]]})
    today = ledger_store.now()[:10]
    ended_today = {s: 0 for s in ("merged", "rejected", "blocked", "failed", "returned")}
    for j in all_jobs:
        if j["state"] in ended_today and str(j.get("updated_at") or "").startswith(today):
            ended_today[j["state"]] += 1
    holds_list = [{"kind": holds_active["kind"][:40], "until": iso(holds_active["until"])}] if holds_active else []
    snap = {"version": 1, "madeAt": iso(now), "beat": beat, "repo": cfg["repo"],
            "jobs": [_job(store, cfg, names, j, completed) for j in kept], "holds": holds_list, "pools": pool_list,
            "endedToday": ended_today, "epics": _epics(store, kept, read_epic),
            "digest": digest.build(store, cfg, now, plan=plan), "runStats": _run_stats(store, now)}
    if machine is not None:
        snap["machine"] = machine
        snap["digest"]["machine"] = machine
    if plan:
        snap["plan"] = plan
    if planning:
        snap["planning"] = [_plan(p) for p in planning[:MAX_PLANS]]
    return snap
