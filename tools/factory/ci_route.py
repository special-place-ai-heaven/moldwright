import json

from backlog import stamp

HOSTED = "ubuntu-latest"
POOL = {c: {"group": "aap-crrr", "labels": ["self-hosted", "linux", c]} for c in ("light", "heavy")}
VARS = {"light": "CI_RUNS_ON_LIGHT", "heavy": "CI_RUNS_ON_HEAVY"}
QUEUED_S = 20


def idle(runners, cls):
    return sum(1 for r in runners if r.get("status") == "online" and not r.get("busy")
               and cls in {(l.get("name") or "").lower() for l in r.get("labels") or []})


def hosted_waiting(queued_runs, now):
    return any(now - stamp(r["created_at"]) > QUEUED_S for r in queued_runs)


def choose(runners, waiting):
    light = POOL["light"] if idle(runners, "light") else HOSTED
    heavy = POOL["heavy"] if waiting and idle(runners, "heavy") else HOSTED
    return {"light": json.dumps(light), "heavy": json.dumps(heavy)}


def poll(gh, org, repo, now):
    runners = json.loads(gh(["api", "orgs/%s/actions/runners?per_page=100" % org]))["runners"]
    queued = json.loads(gh(["api", "repos/%s/actions/runs?status=queued&per_page=20" % repo]))["workflow_runs"]
    return choose(runners, hosted_waiting(queued, now))
