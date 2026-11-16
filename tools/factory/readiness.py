import datetime
import json

import cutshape

OWNERS = ("special-place-ai-heaven", "special-place-administrator")
LABELS = (("factory", "0e8a16"), ("factory-paused", "fbca04"), ("factory-blocked", "d93f0b"), ("factory-done", "5319e7"),
          ("factory-problem", "b60205"), ("factory-plan", "1d76db"), ("likely-fixed", "c5def5"),
          ("P0", "b60205"), ("P1", "d93f0b"), ("P2", "fbca04"), ("P3", "c2e0c6"))
REDGREEN = "Done-test red before green"
PROBE = "factory-probe"
BASE = "dev"


class Stop(Exception):
    pass


def owner(gh, repo, facts):
    who = repo.split("/")[0]
    if who not in OWNERS:
        raise Stop("the factory tools work only for %s, not for %s" % (" and ".join(OWNERS), who))
    return "%s is an owner the factory tools work for" % who


def read(gh, repo, facts):
    info = json.loads(gh(["api", "repos/%s" % repo]))
    facts.update(default=info["default_branch"], push=(info.get("permissions") or {}).get("push") is True)
    if info.get("archived"):
        raise Stop("the repository is archived")
    if not info.get("has_issues"):
        raise Stop("the repository has no issues")
    return "readable; its default branch is %s" % facts["default"]


def push(gh, repo, facts):
    if not facts["push"]:
        raise Stop("the shared token may not push")
    sha = json.loads(gh(["api", "repos/%s/git/ref/heads/%s" % (repo, facts["default"])]))["object"]["sha"]
    try:
        gh(["api", "-X", "POST", "repos/%s/git/refs" % repo, "-f", "ref=refs/heads/" + PROBE, "-f", "sha=" + sha])
    finally:
        left = json.loads(gh(["api", "repos/%s/git/matching-refs/heads/%s" % (repo, PROBE)]))
        if any(r.get("ref") == "refs/heads/" + PROBE for r in left):
            gh(["api", "-X", "DELETE", "repos/%s/git/refs/heads/%s" % (repo, PROBE)])
    return "pushed the branch %s and removed it" % PROBE


def pulls(gh, repo, facts):
    json.loads(gh(["api", "repos/%s/pulls?state=all&per_page=1" % repo]))
    return "pull requests are readable; opening one uses the push right shown above"


def base(gh, repo, facts):
    refs = json.loads(gh(["api", "repos/%s/git/matching-refs/heads/%s" % (repo, BASE)]))
    if any(r.get("ref") == "refs/heads/" + BASE for r in refs):
        facts["base"] = BASE
        return "builds on %s" % BASE
    facts["base"] = facts["default"]
    return "no %s branch: each job builds on its own branch job/<issue> cut from %s, the line merges into that branch, and Rob merges it into %s" % (
        BASE, facts["default"], facts["default"])


def labels(gh, repo, facts):
    have = {x["name"] for x in json.loads(gh(["api", "--paginate", "repos/%s/labels?per_page=100" % repo]))}
    made = []
    for name, color in LABELS:
        if name not in have:
            gh(["api", "-X", "POST", "repos/%s/labels" % repo, "-f", "name=" + name, "-f", "color=" + color])
            made.append(name)
    return "created: " + ", ".join(made) if made else "all %d factory labels are there" % len(LABELS)


def checks(gh, repo, facts):
    n = json.loads(gh(["api", "repos/%s/actions/runs?event=pull_request&per_page=1" % repo])).get("total_count") or 0
    if not n:
        raise Stop("no check has ever run on a pull request: the line merges nothing untested")
    return "pull requests run checks (%d runs so far)" % n


def proof(gh, repo, facts):
    flows = json.loads(gh(["api", "repos/%s/actions/workflows?per_page=100" % repo])).get("workflows") or []
    facts["redgreen"] = any(w.get("name") == REDGREEN and w.get("state") == "active" for w in flows)
    if facts["redgreen"]:
        return 'has the check "%s"' % REDGREEN
    return 'no check "%s": the prover runs the done-test on the base and on the head itself' % REDGREEN


def cut(gh, repo, facts):
    rows = json.loads(gh(["issue", "list", "-R", repo, "--state", "open", "--json", "number,title,body,labels", "--limit", "100"]))
    mine = [i for i in rows if any(x.get("name") == "factory" for x in i.get("labels") or [])]
    bad = sum(1 for e in cutshape.check(mine).values() if e)
    return "%d open issues: %d in the cut format, %d labelled factory and not readable, %d go to the planning station first" % (
        len(rows), len(mine) - bad, bad, len(rows) - len(mine))


STEPS = (("owner", owner, False), ("read", read, False), ("push", push, True), ("pull requests", pulls, False), ("base", base, False),
         ("labels", labels, True), ("checks", checks, False), ("proof", proof, False), ("issues", cut, False))


def check(gh, repo, now):
    facts, lines, stopped = {}, [], False
    for name, step, writing in STEPS:
        if stopped or (writing and not all(x["ok"] for x in lines)):
            lines.append({"name": name, "ok": False, "text": "not checked: an earlier line failed"})
            continue
        try:
            lines.append({"name": name, "ok": True, "text": step(gh, repo, facts)[:200]})
            continue
        except Stop as e:
            text = str(e)
        except Exception as e:
            text = "could not be checked: %s" % (str(e) or type(e).__name__)
        lines.append({"name": name, "ok": False, "text": text[:200]})
        stopped = stopped or name in ("owner", "read")
    return {"repo": repo, "at": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "passed": all(x["ok"] for x in lines), "base": facts.get("base"), "redgreen": bool(facts.get("redgreen")), "lines": lines}
