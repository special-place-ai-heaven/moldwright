import json
import unittest

import factory as F
import lines as L
import readiness as R
from test_dispatch import ready
from test_lines import Pair


class Hub:
    def __init__(self, **over):
        self.repo = dict({"default": "main", "push": True, "archived": False, "has_issues": True, "heads": {"main", "dev"},
                          "labels": {"bug", "factory", "P1"}, "pr_runs": 3, "workflows": [{"name": R.REDGREEN, "state": "active"}],
                          "issues": [{"number": 1, "title": "a", "body": ready(), "labels": [{"name": "factory"}]},
                                     {"number": 2, "title": "b", "body": "no shape", "labels": [{"name": "factory"}]},
                                     {"number": 3, "title": "c", "body": "an idea", "labels": []}]}, **over)
        self.calls, self.fail = [], None

    def writes(self):
        return [a for a in self.calls if "-X" in a]

    def __call__(self, args):
        a = list(args)
        self.calls.append(a)
        r, path = self.repo, a[-1] if a[0] == "api" and "-X" not in a else ""
        if self.fail and any(self.fail in x for x in a):
            raise RuntimeError("gh api failed: exit 1: HTTP 502")
        if a[:2] == ["issue", "list"]:
            return json.dumps(r["issues"])
        if "-X" in a and a[a.index("-X") + 1] == "POST" and a[3].endswith("/git/refs"):
            r["heads"].add(a[5].split("refs/heads/")[1])
            return "{}"
        if "-X" in a and a[a.index("-X") + 1] == "DELETE":
            r["heads"].discard(a[3].split("/heads/")[1])
            return ""
        if "-X" in a and a[3].endswith("/labels"):
            r["labels"].add(a[5].split("=", 1)[1])
            return "{}"
        if "/git/ref/heads/" in path:
            return json.dumps({"object": {"sha": "c" * 40}})
        if "/git/matching-refs/heads/" in path:
            want = path.split("/heads/")[1]
            return json.dumps([{"ref": "refs/heads/" + h} for h in sorted(r["heads"]) if h.startswith(want)])
        if path.endswith("/labels?per_page=100"):
            return json.dumps([{"name": x} for x in sorted(r["labels"])])
        if "/pulls?" in path:
            return "[]"
        if "/actions/runs?event=pull_request" in path:
            return json.dumps({"total_count": r["pr_runs"]})
        if "/actions/workflows" in path:
            return json.dumps({"workflows": r["workflows"]})
        return json.dumps({"default_branch": r["default"], "permissions": {"push": r["push"]}, "archived": r["archived"], "has_issues": r["has_issues"]})


def run(hub, repo="special-place-ai-heaven/x"):
    got = R.check(hub, repo, 1000.0)
    return got, {x["name"]: x for x in got["lines"]}


class Readiness(unittest.TestCase):
    def test_a_ready_project_passes_with_every_line_shown(self):
        hub = Hub()
        got, by = run(hub)
        self.assertEqual([x["name"] for x in got["lines"]], ["owner", "read", "push", "pull requests", "base", "labels", "checks", "proof", "issues"])
        self.assertTrue(all(x["ok"] for x in got["lines"]), got["lines"])
        self.assertEqual((got["passed"], got["base"], got["redgreen"], got["repo"], got["at"]), (True, "dev", True, "special-place-ai-heaven/x", "1970-01-01T00:16:40Z"))
        self.assertEqual(by["read"]["text"], "readable; its default branch is main")
        self.assertEqual(by["issues"]["text"], "3 open issues: 1 in the cut format, 1 labelled factory and not readable, 1 go to the planning station first")

    def test_the_push_is_proven_with_a_branch_that_is_removed_again(self):
        hub = Hub()
        got, by = run(hub)
        self.assertEqual(by["push"]["text"], "pushed the branch factory-probe and removed it")
        self.assertNotIn("factory-probe", hub.repo["heads"])
        hub = Hub(heads={"main", "dev", "factory-probe"})
        run(hub)
        self.assertNotIn("factory-probe", hub.repo["heads"])

    def test_missing_labels_are_created_and_named(self):
        hub = Hub()
        got, by = run(hub)
        self.assertEqual(by["labels"]["text"], "created: factory-paused, factory-blocked, factory-done, factory-problem, factory-plan, likely-fixed, P0, P2, P3")
        self.assertTrue({n for n, _ in R.LABELS} <= hub.repo["labels"])
        self.assertEqual(run(hub)[1]["labels"]["text"], "all 11 factory labels are there")

    def test_an_owner_the_tools_do_not_work_for_is_refused_and_nothing_is_read_or_written(self):
        self.assertEqual(R.OWNERS, F.OWNERS)
        hub = Hub()
        got, by = run(hub, "someone/else")
        self.assertFalse(got["passed"])
        self.assertIn("work only for special-place-ai-heaven and special-place-administrator, not for someone", by["owner"]["text"])
        self.assertEqual(hub.calls, [])
        self.assertEqual({x["text"] for x in got["lines"][1:]}, {"not checked: an earlier line failed"})

    def test_no_push_right_fails_and_writes_nothing(self):
        hub = Hub(push=False)
        got, by = run(hub)
        self.assertEqual((got["passed"], by["push"]["text"], by["labels"]["ok"]), (False, "the shared token may not push", False))
        self.assertEqual(hub.writes(), [])
        self.assertTrue(by["checks"]["ok"])

    def test_no_checks_or_archived_each_fail_with_the_reason(self):
        got, by = run(Hub(pr_runs=0))
        self.assertEqual((got["passed"], by["checks"]["text"]), (False, "no check has ever run on a pull request: the line merges nothing untested"))
        hub = Hub(archived=True)
        got, by = run(hub)
        self.assertEqual((got["passed"], by["read"]["text"], hub.writes()), (False, "the repository is archived", []))

    def test_without_a_dev_branch_the_base_is_the_default_and_the_line_says_where_jobs_merge(self):
        got, by = run(Hub(heads={"main", "develop"}))
        self.assertEqual((got["passed"], got["base"]), (True, "main"))
        self.assertEqual(by["base"]["text"], "no dev branch: each job builds on its own branch job/<issue> cut from main, the line merges into that branch, and Rob merges it into main")

    def test_a_project_without_the_red_green_check_passes_and_says_what_stands_in(self):
        got, by = run(Hub(workflows=[{"name": "CI", "state": "active"}]))
        self.assertEqual((got["passed"], got["redgreen"]), (True, False))
        self.assertIn("the prover runs the done-test on the base and on the head itself", by["proof"]["text"])

    def test_a_call_that_fails_is_a_failed_line_and_the_rest_is_still_shown(self):
        hub = Hub()
        hub.fail = "/actions/runs"
        got, by = run(hub)
        self.assertEqual((got["passed"], by["checks"]["ok"], by["proof"]["ok"]), (False, False, True))
        self.assertIn("could not be checked: gh api failed", by["checks"]["text"])
        self.assertEqual(len(got["lines"]), 9)


class Asked(Pair):
    def new(self):
        d = super().new()
        d.gh = self.hub
        return d

    def setUp(self):
        super().setUp()
        self.hub = Hub()
        self.worlds["special-place-ai-heaven/x"] = self.p
        self.p.ledger = L.ledger_path(self.cfg, "special-place-ai-heaven/x")

    def test_a_check_the_app_asks_for_is_run_recorded_and_reported_and_lets_the_project_be_taken(self):
        self.start(passed=False)
        self.answer["check"] = ["special-place-ai-heaven/x"]
        self.select("special-place-ai-heaven/x")
        self.tick()
        self.assertEqual(self.d.active, "special-place-ai-heaven/x")
        kept = json.loads(self.w.rows("SELECT v FROM kv WHERE job='-' AND k='ready:special-place-ai-heaven/x'")[0][0])
        self.assertEqual(kept, {"passed": True, "at": "1970-01-01T00:16:40Z", "base": "dev", "redgreen": True})
        self.tick()
        shown = self.p.reports[-1]["readiness"]
        self.assertEqual([(x["repo"], x["passed"], len(x["lines"])) for x in shown], [("special-place-ai-heaven/x", True, 9)])

    def test_a_failed_check_is_reported_and_the_project_is_not_taken(self):
        self.hub.repo["pr_runs"] = 0
        self.start(passed=False)
        self.answer["check"] = ["special-place-ai-heaven/x"]
        self.select("special-place-ai-heaven/x")
        self.tick(2)
        self.assertEqual(self.d.active, "o/r")
        self.assertFalse(self.w.reports[-1]["readiness"][0]["passed"])
        self.assertEqual(self.p.sends, [])

    def test_the_same_project_is_checked_at_most_once_a_minute_and_one_project_per_beat(self):
        self.start(passed=False)
        self.answer["check"] = ["special-place-ai-heaven/x", "special-place-ai-heaven/y", 7, "../z"]
        self.tick()
        n = len(self.hub.calls)
        self.assertTrue(all("special-place-ai-heaven/x" in " ".join(a) for a in self.hub.calls))
        self.answer["check"] = ["special-place-ai-heaven/x"]
        self.w.clock += 59
        self.tick()
        self.assertEqual(len(self.hub.calls), n)
        self.w.clock += 1
        self.tick()
        self.assertGreater(len(self.hub.calls), n)

    def test_a_check_that_raises_never_breaks_the_beat(self):
        self.start(passed=False)
        self.d.gh = None
        self.answer["check"] = ["special-place-ai-heaven/x"]
        self.tick(2)
        self.assertEqual(self.state(), "building")
        self.assertFalse(self.w.reports[-1]["readiness"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
