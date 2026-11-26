import re

import states

REASONS = ("dependency", "fact recheck", "no free worker of its type", "back-off", "hold", "plan limit", "sign-in renewal")

_QUEUE_STATES = states.QUEUE
DEPENDENCY_PREFIX = "waits on "


def dependency_numbers(job):
    if job.get("file_wait"):
        return []
    line = job.get("wait_line") or ""
    named = [int(n) for n in re.findall(r"#(\d+)", line)] if line.startswith(DEPENDENCY_PREFIX) else []
    return list(dict.fromkeys([*(job.get("waiting") or []), *named]))


def keep_dependencies(job, unmet):
    kept = dict(job, waiting=unmet)
    line = kept.get("wait_line") or ""
    if line.startswith(DEPENDENCY_PREFIX):
        parts = [p for p in line[len(DEPENDENCY_PREFIX):].split(", ")
                 if (m := re.search(r"#(\d+)", p)) and int(m[1]) in unmet]
        if parts:
            kept["wait_line"] = DEPENDENCY_PREFIX + ", ".join(parts)
        else:
            kept.pop("wait_line", None)
    for key in ("dead", "waits_on_returned"):
        if key in kept:
            kept[key] = [x for x in kept[key] if (x[0] if key == "dead" else x) in unmet]
            if not kept[key]:
                kept.pop(key)
    return kept


def reason(job, now, hold=None, held=(), no_provider=False, work=None):
    state = job.get("state")
    if state == "waiting":
        return "fact recheck" if job.get("recheck") else "dependency"
    if state == "checks":
        return job.get("checks_why")
    if state not in _QUEUE_STATES:
        return None
    not_before = job.get("not_before")
    if not_before is not None and not_before > now:
        return "back-off"
    if hold and hold.get("kind") == "no work" and work and work.get("wait"):
        return work["wait"]
    if work is not None and job.get("issue") not in work.get("issues", ()):
        return "waits its turn in the work order" if job.get("issue") in work.get("order", ()) else "not in the work order"
    if hold:
        kind = hold.get("kind")
        return kind if kind in ("plan limit", "sign-in renewal", "paused", "draining", "stopped") else "hold"
    if no_provider:
        return no_provider if isinstance(no_provider, str) else "no enabled provider"
    if held:
        return "coworker held: " + ", ".join(held)
    return "no free worker of its type"
