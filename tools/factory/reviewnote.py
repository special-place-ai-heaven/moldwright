import datetime, hashlib, re

ADOPT = "ADOPT REVIEW NOTE:"
HEAD = r"[0-9a-f]{40}"
ATTEMPT = r"[0-9a-f]{32}"
COMMENT_ID = r"[1-9][0-9]{0,19}"
REPO = r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*"
REF = re.compile(rf"{ADOPT} ({REPO})#([1-9][0-9]*) ({HEAD}) ({COMMENT_ID}) ([0-9a-f]{{64}})")
ACTOR = (358443129, "moldwright-factory[bot]", 5822204)


def attempt_line(attempt, head):
    return "Review-attempt: %s %s" % (attempt, head)


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def comment_url(repo, pr):
    return "https://github.com/%s/pull/%s#issuecomment-" % (repo, pr)


def reference(repo, pr, head, body, url):
    m = re.fullmatch(re.escape(comment_url(repo, pr)) + "(" + COMMENT_ID + ")", url)
    return "%s %s#%s %s %s %s" % (ADOPT, repo, pr, head, m[1], digest(body)) if m else None


def adopted(out, repo, pr, head):
    lines = [line for line in out.splitlines() if line.strip()]
    verdict = re.fullmatch(r"VERDICT: ACCEPT @([0-9a-f]{7,40})", lines[-1]) if lines else None
    if not verdict or not head.startswith(verdict[1]):
        return None
    refs = [line for line in lines[:-1] if line.lstrip().startswith("ADOPT REVIEW NOTE")]
    ref = REF.fullmatch(refs[0]) if len(refs) == 1 and refs[0] == lines[-2] else None
    return (ref[4], ref[5]) if ref and ref.group(1, 2, 3) == (repo, str(pr), head) else None


def checked_body(note, repo, pr, head, cid, expected_digest, reviewer, attempt, intent, run):
    user, app = note.get("user") or {}, note.get("performed_via_github_app") or {}
    if ((user.get("id"), user.get("login"), app.get("id")) != ACTOR or note.get("id") != int(cid)
            or note.get("issue_url") != "https://api.github.com/repos/%s/issues/%s" % (repo, pr)
            or note.get("html_url") != comment_url(repo, pr) + cid):
        return None
    created_at = note.get("created_at")
    if created_at != note.get("updated_at"):
        return None
    parse = datetime.datetime.fromisoformat
    started = max(parse(intent), parse(run["startedAt"])).replace(microsecond=0)
    if not started <= parse(created_at) <= parse(run["finishedAt"]):
        return None
    body = note.get("body")
    prefix = "Review ACCEPT @%s: %s ACCEPT @%s: " % (head[:8], reviewer, head[:8])
    marker = attempt_line(attempt, head)
    if (not isinstance(body, str) or not body.startswith(prefix) or not body.endswith("\n" + marker)
            or [line for line in body.splitlines() if line.strip().startswith("Review-attempt:")] != [marker]
            or digest(body) != expected_digest):
        return None
    return body[len(prefix):-len(marker) - 1]
