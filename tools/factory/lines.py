import json
import os
import re
import shutil
import stat
import threading
import time
import urllib.parse

import authors
import factory
import limits
import mirror
import pools
import projects
import states
import upload

END = states.END
REPO = projects.REPO
UNPUSHED = ("building", "fixing")
NOT_STARTED = ("waiting", "queued")
CHECK_AGAIN_S = 10 * 60
RECHECK_FLOOR_S = 60
READINESS_PER_HOUR = 20
REPOS_AGAIN_S = 5 * 60
PROBES_KEPT = 10
PROJECT_QUEUE_MAX = 20
UPLOAD_SHA = re.compile(r"[0-9a-f]{64}")
IDENTIFIED_KEYS = ("identified_repo", "head", "dropped")
OWNERS_SHOWN = 20
OWNER_MAX = 100
CONTROL_STATES = ("RUNNING", "PAUSED", "DRAINING", "STOPPED")
CONTROL_DEFAULT = "PAUSED"
CONNECTION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
CONNECTIONS_OFF_MAX = 50
ORDER_KINDS = ("feature", "bug", "issue", "all_issues")
ORDER_ISSUES_MAX = 200
ORDER_TEXT_MAX = 4000
ORDER_ACTIONS = ("retry", "skip")
QUEUE_CLEAR_MAX = 500
QUEUE_CLEAR_TTL_S = 90
FAILED = ("blocked", "failed")
DEPENDENCY_ENDED = re.compile(r"^dependency #[0-9]+ ended [a-z_]+$")
GHOSTS_CEILING = 32
FILE_AGAIN_S = 5 * 60
STATION_MAX = 64
STATIONS_MAX = 64
TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9_.\-]{8,}|github_pat_[A-Za-z0-9_]{8,}|x-access-token:[^@\s]+)")


def scrub(text):
    text = TOKEN.sub("[token]", text)
    decoded = urllib.parse.unquote(text)
    return TOKEN.sub("[token]", decoded) if TOKEN.search(decoded) else text


def station(name):
    return isinstance(name, str) and 0 < len(name) <= STATION_MAX and name.isprintable() and bool(name.strip())


def ceiling():
    try:
        return max(1, int(os.environ.get("FACTORY_MAX_GHOSTS", GHOSTS_CEILING)))
    except ValueError:
        return GHOSTS_CEILING


def whole(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def stamp(at):
    try:
        return limits.ts(str(at))
    except (TypeError, ValueError):
        return None


def ledger_path(cfg, repo):
    if repo == cfg["repo"]:
        return cfg["ledger_file"]
    return os.path.join(os.path.dirname(cfg["ledger_file"]), "ledger-%s.db" % repo.replace("/", "--"))


def line_cfg(cfg, repo):
    if repo == cfg["repo"]:
        return cfg
    path = ledger_path(cfg, repo)
    return dict(cfg, repo=repo, home=cfg["repo"], ledger_file=path, json_state_file=path + ".json")


def live(d):
    return [j for j in d.jobs() if j["state"] not in NOT_STARTED and (j["state"] not in END or not j.get("relabelled"))]


def printable(text):
    return "".join(c if c.isprintable() else " " for c in str(text or ""))[:100]


def unpushed(d):
    return [j for j in d.jobs() if j["state"] in UNPUSHED]


class Lines:
    def __init__(self, cfg, account, gh, now=time.time, make=None, mod=None):
        self.cfg, self.now, self.home, self.account = cfg, now, cfg["repo"], account
        self.mod = mod or __import__("dispatch")
        self.make = make or (lambda c: self.mod.Dispatcher(c, account, gh, now))
        self.lines, self.said, self.last = {}, set(), None
        self.gh, self.repos, self.repos_at, self.probes, self.draining = gh, [], None, {}, []
        self.checks_run, self.future_asks = [], {}
        self.managed, self.cloning, self.unpacking = {}, None, None
        self.leftovers_checked = False
        self.kv = self.open(self.home).store
        self.active = self.home
        saved = self.read("project", {})
        for repo in [saved.get("repo")] + list(self.read("finishing", [])):
            if isinstance(repo, str) and REPO.match(repo) and repo not in self.lines:
                try:
                    self.open(repo)
                except Exception as e:
                    self.problem("project %s not opened: %s" % (repo, e if isinstance(e, RuntimeError) else type(e).__name__))
        if saved.get("repo") in self.lines:
            self.active, self.last = saved["repo"], saved
            self.mend()
        self.roles()

    def read(self, key, default):
        try:
            got = json.loads(self.kv.get_all("-").get(key) or "null")
        except ValueError:
            return default
        return got if isinstance(got, type(default)) else default

    def mend(self):
        raw = self.kv.get_all("-").get("project")
        if not any(e["key"] == "project" and e["to"] == raw for e in self.kv.events()):
            self.kv.add_event("project", self.last.get("from"), raw)
            self.problem("project: the switch to %s had no events row; it is written now" % self.active)

    def open(self, repo):
        self.lines[repo] = self.make(line_cfg(self.cfg, repo))
        return self.lines[repo]

    def roles(self):
        for repo, d in self.lines.items():
            d.taking = d.reporting = repo == self.active
            d.others = (lambda me: lambda: [p for r, x in self.lines.items() if r != me for p in x.own()])(repo)
            d.extra = self.extra if repo == self.active else dict

    def finishing(self):
        return [(r, len(live(d))) for r, d in self.lines.items() if r != self.active and live(d)]

    def control(self):
        saved = self.read("control", {})
        return saved.get("state") if saved.get("state") in CONTROL_STATES else CONTROL_DEFAULT

    def off(self):
        saved = self.read("providers", {}).get("off")
        return sorted(c for c in saved if isinstance(c, str) and CONNECTION_ID.match(c)) if isinstance(saved, list) else []

    def apply_controls(self):
        state, off = self.control(), frozenset(self.off())
        for d in self.lines.values():
            d.run_state, d.off_connections, d.work = state, off, None
            d.cfg["pool"] = self.pool(d)
        self.lines[self.active].work = self.work()

    def throttle(self):
        saved = self.read("throttle", {})
        stations = saved.get("stations") if isinstance(saved.get("stations"), dict) else {}
        return {"max_ghosts": max(1, saved["max_ghosts"]) if whole(saved.get("max_ghosts")) else 1,
                "stations": {k: max(1, v) for k, v in stations.items() if isinstance(k, str) and whole(v)}, "by": saved.get("by"), "at": saved.get("at")}

    def stations(self, d):
        members = {}
        for t in pools.types(d.cfg).values():
            for c in t["coworkers"]:
                members.setdefault(c["name"], set()).add(c["id"])
        settings = d.cfg.get("classify") or {}
        if settings.get("on") and settings.get("agent"):
            members.setdefault(settings.get("agent_name") or "classify", set()).add(settings["agent"])
        return members

    def ghosts(self):
        return [g for d in self.lines.values() for g in d.ghosts()]

    def pool(self, d):
        top, wanted = ceiling(), self.throttle()
        members = self.stations(d)
        return {"max": min(wanted["max_ghosts"], top), "seats": {s: min(wanted["stations"].get(s, 1), top) for s in members},
                "members": members, "ghosts": self.ghosts}

    def learn_throttle(self, ask):
        if ask is None:
            return
        fingerprint = json.dumps(ask, sort_keys=True, default=str)[:4000]
        if self.read("throttle_asked", {}).get("raw") == fingerprint:
            return
        self.kv.set("-", "throttle_asked", json.dumps({"raw": fingerprint}))
        old = self.throttle()
        ask = ask if isinstance(ask, dict) else {}
        at, last = stamp(ask.get("at")), stamp(self.read("throttle", {}).get("asked_at"))
        if at is None:
            return self.problem("throttle answer has no readable at: the pool stays %d" % old["max_ghosts"])
        if last is not None and at <= last:
            return
        top, most, stations = ceiling(), ask.get("max_ghosts", old["max_ghosts"]), ask.get("stations", {})
        if not whole(most) or not isinstance(stations, dict) or len(stations) > STATIONS_MAX:
            return self.problem("throttle answer not understood: the pool stays %d" % old["max_ghosts"])
        known = {s for d in self.lines.values() for s in self.stations(d)}
        stations = {k: v for k, v in stations.items() if station(k) and k in known and whole(v)}
        new = {"max_ghosts": max(1, min(most, top)), "stations": dict(old["stations"], **{k: max(1, min(v, top)) for k, v in stations.items()})}
        if new == {"max_ghosts": old["max_ghosts"], "stations": old["stations"]} and "throttle" in self.kv.get_all("-"):
            return
        self.change("throttle", dict(new, by=printable(ask.get("by")), at=self.mod.iso(self.now()), asked_at=str(ask.get("at"))[:64]),
                    "pool %d, seats %s" % (new["max_ghosts"], ", ".join("%s %d" % kv for kv in sorted(new["stations"].items())) or "default"))

    def file_order(self):
        order = self.order()
        if not order or order["kind"] not in ("feature", "bug") or order.get("filed") or order.get("repo") != self.active or not self.chosen():
            return
        failed = self.read("work_order_filing", {})
        if failed.get("id") == order["id"] and self.now() - (failed.get("t") or 0) < FILE_AGAIN_S:
            return
        d, marker = self.lines[self.active], "Factory work order: %s" % order["id"]
        try:
            found = json.loads(d.gh(["issue", "list", "-R", order["repo"], "--state", "all", "--search", '"%s" in:body' % marker,
                                     "--json", "number,body,author", "--limit", "20"]) or "[]")
            n = next((i["number"] for i in found if isinstance(i, dict) and isinstance(i.get("number"), int)
                      and marker in str(i.get("body") or "").splitlines() and authors.trusted_author(i)), None)
            if n is None:
                title = next((x.strip().lstrip("#").strip() for x in order["text"].splitlines() if x.strip().lstrip("#").strip()), order["kind"])[:256]
                made = d.gh(["issue", "create", "-R", order["repo"], "--title", title, "--body", "%s\n\n%s" % (order["text"].rstrip(), marker), "--label", d.label])
                n = int(made.strip().rsplit("/", 1)[1])
        except (self.mod.Error, ValueError, IndexError, TypeError) as e:
            why = scrub(printable(str(e)))[:200]
            self.kv.set("-", "work_order_filing", json.dumps({"id": order["id"], "t": self.now(), "error": why}))
            return self.mod.log("work_order", "work order %s: issue filing failed: %s" % (order["id"], why))
        self.kv.set("-", "work_order_filing", "{}")
        self.change("work_order", dict(order, filed=n), "work order %s filed as #%d" % (order["id"], n))

    def chosen(self):
        return bool(self.last) and self.last.get("repo") == self.active

    def order(self):
        saved = self.read("work_order", {})
        return saved if saved.get("kind") in ORDER_KINDS else None

    def work(self):
        order = self.order()
        if not self.chosen():
            return {"wait": "no project chosen", "issues": [], "order": []}
        if order is None or order.get("repo") != self.active:
            return {"wait": "no work order", "issues": [], "order": []}
        issues = order.get("issues") or []
        if order["kind"] in ("feature", "bug") and not order.get("filed"):
            failed = self.read("work_order_filing", {})
            wait = "issue filing failed: %s" % failed.get("error") if failed.get("id") == order["id"] else "filing issue"
            return {"wait": wait, "issues": [], "order": issues}
        if order["kind"] in ("feature", "bug"):
            issues = [order["filed"]]
        store, skipped, retried, done, picked, waiting = self.lines[self.active].store, order.get("skipped", []), order.get("retried", {}), [], [], []
        most = max(1, min(self.throttle()["max_ghosts"], ceiling()))
        for n in issues:
            j, kv = store.get_job(str(n)) or {}, store.get_all(str(n))
            if n in skipped or (j.get("state") in (None, "cancelled") and kv.get("closed_unstarted")) or (order["kind"] == "all_issues" and kv.get("order_paused")) or (
                    j.get("state") == "blocked" and DEPENDENCY_ENDED.match(j.get("reason") or "")):
                done.append(n)
                continue
            if j.get("state") in FAILED and retried.get(str(n)) != j.get("take", 1):
                return {"wait": "job #%d failed: retry or skip" % n, "issues": picked, "order": issues, "done": done, "halted": n, "skipped": skipped}
            if j.get("state") in states.END and j.get("state") not in FAILED + ("cancelled",):
                done.append(n)
                continue
            if j.get("state") == "waiting":
                waiting.append(n)
                continue
            wait = None
            if not j and kv.get("order_paused"):
                wait = "issue #%d is labelled factory-paused" % n
            elif not j and kv.get("cutshape"):
                wait = "issue #%d body is not cut-shaped" % n
            if wait and picked:
                break
            picked.append(n)
            if wait or len(picked) >= most:
                return {"wait": wait, "issues": picked, "order": issues, "done": done, "skipped": skipped}
        if picked or waiting:
            return {"wait": None, "issues": picked, "order": issues, "done": done, "skipped": skipped}
        return {"wait": "the work order is done", "issues": [], "order": issues, "done": done, "skipped": skipped}

    def learn_action(self, ask):
        if ask is None:
            return
        fingerprint = json.dumps(ask, sort_keys=True, default=str)[:2000]
        if self.read("work_order_action_asked", {}).get("raw") == fingerprint:
            return
        self.kv.set("-", "work_order_action_asked", json.dumps({"raw": fingerprint}))
        order, ask = self.order(), ask if isinstance(ask, dict) else {}
        action, n = ask.get("action"), ask.get("issue")
        if action not in ORDER_ACTIONS or order is None or ask.get("order_id") != order.get("id") or not isinstance(n, int) or isinstance(n, bool):
            return self.problem("work order action not understood: nothing changes")
        if self.work().get("halted") != n:
            return self.problem("work order action %s on #%d not taken: that job is not halted" % (action, n))
        if action == "retry":
            take = (self.lines[self.active].store.get_job(str(n)) or {}).get("take", 1)
            order = dict(order, retried=dict(order.get("retried", {}), **{str(n): take}))
        else:
            order = dict(order, skipped=order.get("skipped", []) + [n])
        self.change("work_order", dict(order, by=printable(ask.get("by")), at=self.mod.iso(self.now())), "work order %s: %s #%d" % (order["id"], action, n))

    def learn_clear(self, ask):
        if ask is None:
            return
        fingerprint = json.dumps(ask, sort_keys=True, default=str)[:8000]
        if self.read("queue_clear_asked", {}).get("raw") == fingerprint:
            return
        self.kv.set("-", "queue_clear_asked", json.dumps({"raw": fingerprint}))
        ask = ask if isinstance(ask, dict) else {}
        issues, at = ask.get("issues"), stamp(str(ask.get("at"))[:64])
        if (not isinstance(ask.get("id"), str) or not CONNECTION_ID.match(ask["id"]) or not isinstance(ask.get("repo"), str) or not REPO.match(ask["repo"])
                or not isinstance(issues, list) or not 0 < len(issues) <= QUEUE_CLEAR_MAX or len(set(issues)) != len(issues)
                or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in issues) or at is None):
            return self.problem("queue clear not understood: nothing is cleared")
        last = stamp(self.read("queue_clear", {}).get("asked_at"))
        if last is not None and at <= last:
            return
        by, now = printable(ask.get("by")), self.mod.iso(self.now())
        refused = "expired" if self.now() - at > QUEUE_CLEAR_TTL_S else "wrong_project" if ask["repo"] != self.active else None
        if refused:
            return self.change("queue_clear", {"id": ask["id"], "repo": ask["repo"], "outcome": refused, "cleared": [], "kept": [], "by": by, "at": now, "asked_at": str(ask.get("at"))[:64]},
                               "queue clear for %s not taken: %s, the factory is on %s" % (ask["repo"], refused.replace("_", " "), self.active))
        cleared, kept = self.lines[self.active].clear_pending(issues)
        order, ordered = self.order(), self.work().get("order") or []
        skip = [n for n in cleared if n in ordered and n not in (order or {}).get("skipped", [])]
        if skip:
            self.change("work_order", dict(order, skipped=order.get("skipped", []) + skip, by=by, at=now),
                        "work order %s: skip %s, cleared from the queue" % (order["id"], ", ".join("#%d" % n for n in skip)))
        self.change("queue_clear", {"id": ask["id"], "repo": ask["repo"], "outcome": "cleared", "cleared": cleared, "kept": kept, "by": by, "at": now, "asked_at": str(ask.get("at"))[:64]},
                    "queue cleared in %s: %d cleared, %d kept" % (ask["repo"], len(cleared), len(kept)))

    def learn_order(self, ask):
        if ask is None:
            return
        fingerprint = json.dumps(ask, sort_keys=True, default=str)[:20000]
        if self.read("work_order_asked", {}).get("raw") == fingerprint:
            return
        kind = ask.get("kind") if isinstance(ask, dict) else None
        if kind == "none":
            self.kv.set("-", "work_order_asked", json.dumps({"raw": fingerprint}))
            if self.order() is not None:
                old = self.order()
                self.change("work_order", {"kind": "none", "by": printable(ask.get("by")), "at": self.mod.iso(self.now())},
                            "work order %s cancelled" % old.get("id"))
            return
        order = self.valid_order(ask)
        if order is None:
            return self.problem("work order answer not understood: the work order stays %s" % ((self.order() or {}).get("id") or "none"))
        self.kv.set("-", "work_order_asked", json.dumps({"raw": fingerprint}))
        self.change("work_order", dict(order, by=printable(ask.get("by")), at=self.mod.iso(self.now()), asked_at=str(ask.get("at"))[:64]),
                    "work order %s: %s %s in %s" % (order["id"], order["kind"], ", ".join("#%d" % n for n in order["issues"]) or "-", order["repo"]))

    def valid_order(self, ask):
        kind, issues, text = ask.get("kind"), ask.get("issues", []), ask.get("text", "")
        if kind not in ORDER_KINDS or not isinstance(ask.get("id"), str) or not CONNECTION_ID.match(ask["id"]):
            return None
        if not isinstance(ask.get("repo"), str) or not REPO.match(ask["repo"]) or not isinstance(text, str) or len(text) > ORDER_TEXT_MAX:
            return None
        if not isinstance(issues, list) or len(issues) > ORDER_ISSUES_MAX or len(set(issues)) != len(issues):
            return None
        if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in issues):
            return None
        if (kind == "issue" and len(issues) != 1) or (kind == "all_issues" and not issues) or (kind in ("feature", "bug") and not text.strip()):
            return None
        return {"id": ask["id"], "repo": ask["repo"], "kind": kind, "issues": issues, "text": text}

    def change(self, key, value, said):
        old = self.kv.get_all("-").get(key)
        new = json.dumps(value)
        self.kv.set("-", key, new)
        self.kv.add_event(key, old, new)
        self.mod.log(key, "%s by %s at %s" % (said, value["by"] or "?", value["at"]))

    def learn_control(self, ask):
        if ask is None:
            return
        state = ask.get("state") if isinstance(ask, dict) else None
        if state not in CONTROL_STATES:
            return self.problem("control answer not understood: the factory stays %s" % self.control())
        asked = {"state": state, "by": printable(ask.get("by")), "at": str(ask.get("at"))[:64]}
        if self.read("control_asked", {}) == asked:
            return
        self.kv.set("-", "control_asked", json.dumps(asked))
        at, last = stamp(asked["at"]), stamp(self.read("control", {}).get("asked_at"))
        if at is None:
            return self.problem("control answer has no readable at: the factory stays %s" % self.control())
        if last is not None and at <= last:
            return
        order = self.order()
        newer = order is None or stamp(order.get("asked_at")) is None or at > stamp(order.get("asked_at"))
        if state in ("DRAINING", "STOPPED") and order is not None and newer:
            self.change("work_order", {"kind": "none", "by": printable(ask.get("by")), "at": self.mod.iso(self.now())},
                        "work order %s cancelled by the stop" % self.order().get("id"))
        old = self.control()
        if state == old and "control" in self.kv.get_all("-"):
            self.kv.set("-", "control", json.dumps(dict(self.read("control", {}), asked_at=asked["at"])))
            return
        self.change("control", {"state": state, "by": printable(ask.get("by")), "at": self.mod.iso(self.now()), "asked_at": asked["at"]}, "%s -> %s" % (old, state))

    def drained(self):
        if self.control() != "DRAINING" or any(d.store.running() or d.store.pending() for d in self.lines.values()):
            return
        self.change("control", {"state": "STOPPED", "by": "factory", "at": self.mod.iso(self.now())}, "DRAINING -> STOPPED")

    def learn_providers(self, ask):
        if ask is None:
            return
        off = ask.get("off") if isinstance(ask, dict) else None
        if not isinstance(off, list) or len(off) > CONNECTIONS_OFF_MAX or not all(isinstance(c, str) and CONNECTION_ID.match(c) for c in off):
            return self.problem("providers answer not understood: the connections stay as they are")
        off = sorted(set(off))
        if off == self.off() and "providers" in self.kv.get_all("-"):
            return
        self.change("providers", {"off": off, "by": printable(ask.get("by")), "at": self.mod.iso(self.now())},
                    "connections off: %s (were %s)" % (", ".join(off) or "none", ", ".join(self.off()) or "none"))

    def extra(self):
        out = {"home": self.home, "finishing": [{"repo": r, "jobs": n} for r, n in self.finishing()][:10]}
        saved = self.read("control", {})
        out["control"] = {"state": self.control(), "by": saved.get("by"), "at": saved.get("at")}
        listed = (self.lines[self.active].connections or {}).get("connections") if isinstance(self.lines[self.active].connections, dict) else None
        ids = sorted(c["id"] for c in listed or [] if isinstance(c, dict) and isinstance(c.get("id"), str))
        out["providers"] = {"off": self.off(), "enabled": [c for c in ids if c not in self.off()]}
        order, work = self.order() or {}, self.work()
        out["work_order"] = {"id": order.get("id"), "repo": order.get("repo"), "kind": order.get("kind"), "issues": order.get("issues", []),
                             "text": order.get("text"), "by": order.get("by"), "at": order.get("at"), "current": (work["issues"] or [None])[0],
                             "done": work.get("done", []), "skipped": order.get("skipped", []), "halted": work.get("halted"), "wait": work["wait"]}
        pool, ghosts, wanted = self.lines[self.active].cfg.get("pool") or self.pool(self.lines[self.active]), self.ghosts(), self.throttle()
        out["throttle"] = {"max_ghosts": pool["max"], "ghosts_running": len(ghosts), "max_ghosts_ceiling": ceiling(), "by": wanted["by"], "at": wanted["at"],
                           "stations": {s: {"max": pool["seats"][s], "running": sum(1 for a, _ in ghosts if a in m)} for s, m in sorted(pool["members"].items())}}
        cleared = self.read("queue_clear", {})
        if cleared.get("id"):
            out["queue_clear"] = {k: cleared.get(k) for k in ("id", "repo", "outcome", "cleared", "kept", "at")}
        if self.last:
            out["switch"] = self.last
        owners = [o for o in self.owners() if isinstance(o, str) and len(o) <= OWNER_MAX][:OWNERS_SHOWN]
        out["projects"] = dict(projects.report(self.repos, self.readiness(), list(self.probes.values())), items=self.project_items(), owners=owners)
        return out

    def project_items(self):
        known = sorted(self.managed.items(), key=lambda kv: int(kv[0]))[:projects.ITEMS_MAX]
        return [dict({"id": int(pid), "state": m["state"], "progress": None, "error_code": m["error_code"]},
                     **{k: m[k] for k in IDENTIFIED_KEYS if k in m and m["state"] == "cloning"}) for pid, m in known]

    def learn_projects(self, p):
        if not isinstance(p, dict):
            return
        ws = projects.project_id(p.get("workspace_id"))
        if ws is None:
            return self.problem("projects answer not understood: no project is processed")
        pinned = self.read("workspace", "")
        if not pinned:
            self.kv.set("-", "workspace", json.dumps(ws))
            pinned = ws
        if ws != pinned:
            return self.problem("projects: the hub answers for workspace %s, but this factory serves workspace %s; no project is processed" % (ws, pinned))
        if not self.leftovers_checked:
            self.leftovers_checked = True
            for name in self.folder_names(ws):
                self.drop_leftovers(ws, name)
        listed = p.get("ids") if isinstance(p.get("ids"), list) else []
        ids = {i for i in (projects.project_id(x) for x in listed[:projects.ITEMS_MAX]) if i}
        queue = [q for q in (p.get("queue") if isinstance(p.get("queue"), list) else [])[:PROJECT_QUEUE_MAX] if isinstance(q, dict)]
        queued = {projects.project_id(q.get("id")) for q in queue}
        quota = projects.limits(p.get("limits"))
        self.finish_clone(quota)
        self.finish_unpack(quota)
        for pid in list(self.managed):
            if pid not in ids or (self.managed[pid]["state"] == "failed" and pid not in queued):
                self.managed.pop(pid)
        self.sweep_projects(ws, ids)
        for pid in sorted(ids - set(self.managed)):
            meta = projects.read_meta(projects.project_dir(ws, pid, ws))
            if meta:
                self.managed[pid] = {"state": "ready", "error_code": None, "bytes": meta["bytes"], "repo": meta.get("repo")}
        for q in queue:
            self.take_project(ws, q, ids, quota)
        for pid, m in sorted(self.managed.items()):
            if m.get("pending") and not self.cloning:
                self.begin_clone(ws, pid, m, quota)

    def take_project(self, ws, q, ids, quota):
        pid, repo, source = projects.project_id(q.get("id")), q.get("repo"), q.get("source")
        if pid is None or pid not in ids or pid in self.managed or source not in ("github", "upload"):
            return
        if source == "upload" and q.get("state") != "cloning":
            return self.take_upload(ws, pid, q, quota)
        code = self.project_refusal(repo, quota)
        if code:
            return self.fail_project(pid, code)
        if not self.cloning:
            self.begin_clone(ws, pid, {"source": source, "pending": repo}, quota)

    def begin_clone(self, ws, pid, m, quota):
        repo = m["pending"]
        d = projects.project_dir(ws, pid, ws)
        if d is None:
            return self.fail_project(pid, "unknown")
        if quota and self.size_refusal(repo, quota):
            return self.fail_project(pid, "quota_exceeded")
        existed = os.path.isdir(mirror.path(factory.folder(repo)))
        try:
            proc = projects.start_clone(d, repo)
        except OSError as e:
            self.problem("project %s not cloned: %s" % (pid, type(e).__name__))
            return self.fail_project(pid, "unknown")
        self.cloning = (pid, proc, d, repo, existed)
        self.managed[pid] = dict({k: v for k, v in m.items() if k != "pending"}, state="cloning", error_code=None)
        self.mod.log("project", "project %s: cloning %s into the mirror" % (pid, repo))

    def take_upload(self, ws, pid, q, quota):
        size, sha = q.get("bytes"), q.get("sha256")
        whole = isinstance(size, int) and not isinstance(size, bool) and size >= 0 and isinstance(sha, str) and UPLOAD_SHA.fullmatch(sha)
        if q.get("state") != "queued" or not whole or not callable(getattr(self.account, "archive", None)):
            return self.fail_project(pid, "unknown")
        code = self.space_refusal(quota)
        if code is None and size > quota["upload_max_mb"] * projects.MB:
            code = "upload_too_large"
        if code:
            return self.fail_project(pid, code)
        d = projects.project_dir(ws, pid, ws)
        if d is None:
            return self.fail_project(pid, "unknown")
        if self.unpacking:
            return
        got, owners = {}, self.owners()
        worker = threading.Thread(target=lambda: got.update(upload.receive(self.account.archive, pid, d, size, sha, quota, owners)), daemon=True)
        worker.start()
        self.unpacking = (pid, worker, got)
        self.managed[pid] = {"state": "queued", "error_code": None, "source": "upload"}
        self.mod.log("project", "project %s: fetching and unpacking the uploaded folder" % pid)

    def finish_unpack(self, quota):
        if not self.unpacking or self.unpacking[1].is_alive():
            return
        pid, _, got = self.unpacking
        self.unpacking = None
        if pid not in self.managed:
            return
        if not got.get("ok"):
            return self.fail_project(pid, got.get("code") or "unknown")
        repo = got["repo"]
        code = self.project_refusal(repo, quota)
        if code:
            return self.fail_project(pid, code)
        self.managed[pid] = {"state": "unpacking", "error_code": None, "source": "upload", "pending": repo,
                             "identified_repo": repo, "head": got["head"], "dropped": got["dropped"]}
        self.mod.log("project", "project %s: the uploaded folder is %s, %d sensitive files left out" % (pid, repo, len(got["dropped"])))

    def project_refusal(self, repo, quota):
        if not projects.safe_repo(repo):
            return "invalid_link"
        if repo.split("/")[0] not in self.owners():
            return "owner_not_allowed"
        return self.space_refusal(quota)

    def ready_bytes(self):
        return sum(m.get("bytes", 0) for m in self.managed.values() if m["state"] == "ready")

    def space_refusal(self, quota):
        if quota is None:
            return "quota_unset"
        if projects.free_gb() < factory.MIN_FREE_GB:
            return "disk_low"
        if self.ready_bytes() >= quota["max_total_mb"] * projects.MB:
            return "quota_exceeded"
        return None

    def size_refusal(self, repo, quota):
        try:
            kib = int(self.github(["api", "repos/" + repo, "--jq", ".size"]).strip())
        except Exception:
            return None
        room = min(quota["max_project_mb"] * projects.MB, quota["max_total_mb"] * projects.MB - self.ready_bytes())
        return "quota_exceeded" if kib * 1024 > room else None

    def busy(self, pid):
        return any(work and work[0] == pid for work in (self.cloning, self.unpacking))

    def folder_names(self, ws):
        try:
            return os.listdir(os.path.join(projects.projects_root(), ws))
        except OSError:
            return []

    def drop_leftovers(self, ws, pid):
        d = projects.project_dir(ws, pid, ws)
        if d is None or self.busy(pid):
            return
        try:
            names = os.listdir(d)
        except OSError:
            return
        for name in names:
            path = os.path.join(d, name)
            if (name == "incoming" or name.startswith("tmp-")) and stat.S_ISDIR(os.lstat(path).st_mode):
                shutil.rmtree(path, ignore_errors=True)

    def fail_project(self, pid, code):
        self.managed[pid] = {"state": "failed", "error_code": code}
        self.mod.log("project", "project %s failed: %s" % (pid, code))
        ws = self.read("workspace", "")
        if ws:
            self.drop_leftovers(ws, pid)

    def fail_clone(self, pid, code, repo, existed):
        self.fail_project(pid, code)
        if not existed:
            self.drop_mirror(pid, repo)

    def drop_mirror(self, pid, repo):
        name = factory.folder(repo)
        others = [m.get(k) for p, m in self.managed.items() if p != pid for k in ("repo", "pending", "identified_repo")]
        if any(isinstance(r, str) and factory.folder(r) == name for r in others + [self.home, self.active] + list(self.lines)):
            return
        shutil.rmtree(mirror.path(name), ignore_errors=True)
        self.mod.log("project", "project %s: the mirror this clone made of %s is removed" % (pid, repo))

    def finish_clone(self, quota):
        rc = self.cloning[1].poll() if self.cloning else None
        if rc is None:
            return
        pid, _, d, repo, existed = self.cloning
        self.cloning = None
        code = self.clone_log(d)
        if pid not in self.managed:
            return
        if rc:
            return self.fail_clone(pid, code, repo, existed)
        cache = mirror.path(factory.folder(repo))
        if not os.path.isdir(cache):
            self.managed.pop(pid)
            return self.mod.log("project", "project %s: the mirror of %s is not there yet; it is cloned again" % (pid, repo))
        size = projects.tree_bytes(cache) + projects.tree_bytes(os.path.join(d, "src"))
        if quota is None:
            return self.fail_project(pid, "quota_unset")
        if size > quota["max_project_mb"] * projects.MB:
            return self.fail_clone(pid, "quota_exceeded", repo, existed)
        projects.write_meta(d, {"owner": repo.split("/")[0], "repo": repo, "source": self.managed[pid].get("source", "github"), "bytes": size, "at": self.mod.iso(self.now())})
        self.managed[pid] = {"state": "ready", "error_code": None, "bytes": size, "repo": repo}
        self.mod.log("project", "project %s: %s is ready" % (pid, repo))

    def clone_log(self, d):
        log = os.path.join(d, "clone.log")
        try:
            with open(os.open(log, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8", errors="replace") as f:
                text = f.read()
            with open(os.open(log, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW), "w", encoding="utf-8") as f:
                f.write(scrub(text))
        except OSError:
            return "unknown"
        return projects.clone_code(text)

    def sweep_projects(self, ws, ids):
        for name in self.folder_names(ws):
            d = projects.project_dir(ws, name, ws)
            if d is None or name in ids or self.busy(name):
                continue
            shutil.rmtree(d, ignore_errors=True)
            self.mod.log("project", "project %s: its folder is removed, the hub no longer has it" % name)

    def owners(self):
        return tuple(self.cfg.get("project_owners") or factory.OWNERS)

    def github(self, args):
        return (self.gh or self.lines[self.home].gh)(args)

    def readiness(self):
        out = []
        for k, v in sorted(self.kv.get_all("-").items()):
            if not k.startswith("ready:"):
                continue
            try:
                r = json.loads(v)
                out.append(projects.Readiness(k[len("ready:"):], r["passed"] is True, tuple(projects.Line(**x) for x in r["lines"]), r["at"]))
            except (ValueError, KeyError, TypeError):
                continue
        return out[:20]

    def record(self, repo, by=""):
        now = self.now()
        done = self.checked_at(repo)
        if done is not None and now - done < RECHECK_FLOOR_S:
            return
        self.checks_run = [t for t in self.checks_run if now - t < 3600]
        if len(self.checks_run) >= READINESS_PER_HOUR:
            return self.problem("project %s not checked: %d readiness checks per hour is the cap" % (repo, READINESS_PER_HOUR))
        self.checks_run.append(now)
        try:
            got = projects.readiness(self.github, repo, self.now(), owners=self.owners())
        except Exception as e:
            return self.problem("project %s not checked: %s" % (repo, type(e).__name__))
        self.kv.set("-", "ready:" + repo, json.dumps(projects.serialize(got)))
        failed = [x.name for x in got.lines if not x.ok]
        self.mod.log("project", "readiness of %s%s: %s" % (repo, " asked by %s" % by if by else "", "passed" if got.passed else "failed at %s" % ", ".join(failed)))

    def checked_at(self, repo):
        at = self.read("ready:" + repo, {}).get("at")
        try:
            return limits.ts(at) if isinstance(at, str) else None
        except ValueError:
            return None

    def asked_at(self, asked):
        try:
            at = limits.ts(asked) if isinstance(asked, str) else None
        except ValueError:
            return None
        if at is None or at <= self.now():
            return at
        if asked not in self.future_asks:
            while len(self.future_asks) >= PROBES_KEPT:
                self.future_asks.pop(next(iter(self.future_asks)))
            self.future_asks[asked] = self.now()
        return self.future_asks[asked]

    def fresh(self, done, asked):
        return done is not None and (asked is None or done >= asked - RECHECK_FLOOR_S)

    def check(self, ask):
        if not isinstance(ask, dict):
            return
        if isinstance(ask.get("path"), str):
            got = projects.probe(ask["path"], self.cfg.get("project_root"))
            self.probes.pop(got.path, None)
            self.probes[got.path] = got
            while len(self.probes) > PROBES_KEPT:
                self.probes.pop(next(iter(self.probes)))
            return
        repo = ask.get("repo")
        if not isinstance(repo, str) or not REPO.match(repo):
            return self.problem("project check not understood: nothing is checked")
        done, asked = self.checked_at(repo), self.asked_at(ask.get("at"))
        if done is None or (asked is not None and done < asked) or (asked is None and self.now() - done >= CHECK_AGAIN_S):
            self.record(repo, printable(ask.get("by")))

    def list_repos(self):
        if self.repos_at is not None and self.now() - self.repos_at < REPOS_AGAIN_S:
            return
        self.repos_at = self.now()
        try:
            self.repos = projects.accessible(self.github, self.owners())
        except Exception as e:
            self.problem("repositories the factory can reach not read: %s" % type(e).__name__)

    def problem(self, text):
        if text not in self.said:
            self.said.add(text)
            self.mod.log("-", text)

    def ready(self, repo, asked=None, by=""):
        if repo == self.home:
            return True
        if asked is not None and not self.fresh(self.checked_at(repo), asked):
            self.record(repo, by)
        fresh = asked is None or self.fresh(self.checked_at(repo), asked)
        return fresh and self.read("ready:" + repo, {}).get("passed") is True

    def drain(self):
        waiting = [(r, len(unpushed(d))) for r, d in self.lines.items() if r != self.active and unpushed(d)]
        self.lines[self.active].taking = not waiting
        if self.draining and not waiting:
            self.mod.log("project", "%s starts: %s has no job left to push" % (self.active, ", ".join(r for r, _ in self.draining)))
        elif waiting and waiting != self.draining:
            self.mod.log("project", "%s waits: %s" % (self.active, "; ".join("%d jobs of %s to push" % (n, r) for r, n in waiting)))
        self.draining = waiting

    def once(self):
        self.file_order()
        self.apply_controls()
        self.drain()
        self.lines[self.active].once()
        for repo in [r for r in self.lines if r != self.active]:
            if live(self.lines[repo]):
                self.lines[repo].once()
            elif repo != self.home:
                self.lines.pop(repo).close()
        self.kv.set("-", "finishing", json.dumps([r for r, _ in self.finishing()]))
        before = self.control()
        self.learn(self.lines[self.active].answer)
        self.apply_controls()
        if self.control() == "DRAINING":
            for d in self.lines.values():
                d.clear_queue()
        self.drained()
        self.apply_controls()
        if self.control() == "STOPPED":
            for d in self.lines.values():
                d.stop_running()
        if self.control() != before and self.lines[self.active].reporting:
            self.lines[self.active].report_line()
            self.learn(self.lines[self.active].answer)

    def learn(self, answer):
        if isinstance(answer, dict):
            self.learn_providers(answer.get("providers"))
            self.learn_order(answer.get("work_order"))
            self.learn_action(answer.get("work_order_action"))
            self.learn_clear(answer.get("queue_clear"))
            self.learn_throttle(answer.get("throttle"))
            self.learn_control(answer.get("control"))
            self.check(answer.get("check"))
            self.learn_projects(answer.get("projects"))
            if answer.get("repos"):
                self.list_repos()
        if answer is None or (isinstance(answer, dict) and answer.get("project") is None):
            return
        p = answer.get("project") if isinstance(answer, dict) else None
        repo = p.get("repo") if isinstance(p, dict) else None
        if not isinstance(repo, str) or not REPO.match(repo):
            return self.problem("project answer not understood: the factory stays on %s" % self.active)
        by = printable(p.get("by"))
        if repo == self.active:
            if not self.chosen():
                self.last = {"repo": repo, "from": None, "by": by, "at": self.mod.iso(self.now())}
                self.kv.set("-", "project", json.dumps(self.last))
                self.kv.add_event("project", None, json.dumps(self.last))
                self.mod.log("project", "%s chosen by %s" % (repo, by or "?"))
            return
        if not self.ready(repo, self.asked_at(p.get("at")), by):
            return self.problem("project %s not taken: its readiness is not recorded as passed here; the factory stays on %s (picked by %s)" % (repo, self.active, by or "?"))
        try:
            if repo not in self.lines:
                self.open(repo)
        except Exception as e:
            return self.problem("project %s not taken: %s; the factory stays on %s (picked by %s)" % (repo, e if isinstance(e, RuntimeError) else type(e).__name__, self.active, by or "?"))
        old, self.active = self.active, repo
        self.last = {"repo": repo, "from": old, "by": by, "at": self.mod.iso(self.now())}
        self.roles()
        self.kv.set("-", "project", json.dumps(self.last))
        self.kv.add_event("project", old, json.dumps(self.last))
        self.said.clear()
        self.mod.log("project", "%s -> %s by %s; finishing %d jobs of %s" % (old, repo, self.last["by"] or "?", len(live(self.lines[old])), old))

    @property
    def refresh_to(self):
        return self.lines[self.active].refresh_to

    def close(self):
        for d in self.lines.values():
            d.close()
