def _coworkers(items):
    return [dict({"id": c["id"], "name": c["name"], "runs": c.get("runs", 1)}, **({"provider": c["provider"]} if c.get("provider") else {}))
            for c in items]


def types(cfg):
    if "types" in cfg:
        return {t: {"coworkers": _coworkers(v.get("coworkers", [])),
                    "max_jobs": v.get("max_jobs")}
                for t, v in cfg["types"].items()}
    return {
        "coder": {"coworkers": _coworkers(cfg.get("builders", [])),
                  "max_jobs": cfg.get("max_jobs")},
        "reviewer": {"coworkers": _coworkers(cfg.get("reviewers", [])),
                     "max_jobs": None},
    }


def role(cfg, worker):
    return ((cfg.get("types") or {}).get(worker) or {}).get("role", "build")


def build_pool(cfg, worker):
    return "coder" if role(cfg, worker) == "review" else worker


def review_pool(cfg, worker):
    return worker if role(cfg, worker) == "review" else "reviewer"


def names(cfg):
    return {c["id"]: c["name"] for t in types(cfg).values() for c in t["coworkers"]}


def pick(cfg, worker, busy):
    t = types(cfg).get(worker)
    if t is None:
        return None
    return next((c["id"] for c in t["coworkers"] if c["id"] not in busy), None)


def max_jobs(cfg, worker):
    t = types(cfg).get(worker)
    return None if t is None else t["max_jobs"]


def provider_of(cfg, agent):
    for t in types(cfg).values():
        for c in t.get("coworkers", []):
            if c.get("id") == agent:
                return c.get("provider") or "claude"
    return "claude"


def room(cfg, name=None):
    pool = cfg.get("pool")
    if not pool:
        return None
    ghosts = pool["ghosts"]()
    left = pool["max"] - len(ghosts)
    if name is None:
        return left
    ids = pool["members"].get(name, set())
    return min(left, pool["seats"].get(name, 0) - sum(1 for a, _ in ghosts if a in ids))


def copies(cfg, c):
    return c["runs"] if not cfg.get("pool") else cfg["pool"]["seats"].get(c["name"], 0)


def seats(cfg, worker):
    t = types(cfg).get(worker)
    return sum(copies(cfg, c) for c in t["coworkers"]) if t else 0


def free_copies(cfg, worker, running, exclude=()):
    t = types(cfg).get(worker)
    if t is None or cfg.get("held"):
        return []
    left = room(cfg)
    if left is not None and left <= 0:
        return []
    out = []
    off = set(cfg.get("off_agents") or ())
    for c in [c for c in t["coworkers"] if c["id"] not in exclude and c["id"] not in off]:
        if cfg.get("held_plan") and (c.get("provider") or "claude") == "claude":
            continue
        taken = {1 if k is None else k for i, k in running if i == c["id"]}
        most = copies(cfg, c)
        if len([1 for i, _ in running if i == c["id"]]) >= most or (left is not None and room(cfg, c["name"]) <= 0):
            continue
        out += [(c["id"], n) for n in range(1, most + 1) if n not in taken]
    return out


def pick_copy(cfg, worker, running, exclude=()):
    got = free_copies(cfg, worker, running, exclude)
    return got[0] if got else None
