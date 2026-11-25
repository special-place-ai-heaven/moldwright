import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch as D
from test_dispatch import Base, HEAD, wf

SHA = "feedface12345678"
PARENT = "beef000011112222"


def parent_run(conclusion, number, **extra):
    run = dict(wf("ci", conclusion), head_sha=PARENT, head_branch="dev", event="push", run_number=number, run_attempt=1)
    return {**run, **extra}


class DevResult(Base):
    def merged(self):
        self.to_checks()
        self.w.workflows[HEAD] = [wf("ci", "success")]
        self.tick()
        self.assertEqual(self.state(), "merged")

    def data(self):
        return json.loads(self.w.rows("SELECT data FROM jobs WHERE job='5'")[0][0])

    def commit_reads(self):
        return [c for c in self.w.gh_calls if c[:2] == ["pr", "view"] and "mergeCommit" in c[-1]]

    def push_reads(self):
        return [c for c in self.w.gh_calls if c[0] == "api" and "head_sha=" + SHA in c[1]]

    def test_the_merge_commit_is_read_once_and_kept(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", None, status="in_progress")]
        self.tick(3)
        self.assertEqual(len(self.commit_reads()), 1)
        self.assertEqual(self.data()["merge_sha"], SHA)
        self.assertTrue(self.data()["own_merge"])

    def test_no_result_while_the_push_runs_of_the_merge_commit_are_running(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "success", wid=1), wf("Factory tools", None, status="in_progress", wid=2)]
        self.tick(2)
        self.assertNotIn("dev_result", self.data())

    def test_all_push_runs_passed_is_green(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "success", wid=1), wf("Factory tools", "success", wid=2)]
        self.tick(2)
        self.assertEqual(self.data()["dev_result"], "green")
        self.assertIn("dev green at feedfac", self.out.getvalue())

    def test_a_failed_push_run_is_red_with_its_name(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "success", wid=1), wf("Factory tools", "failure", wid=2)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")
        self.assertIn("Factory tools", self.data()["dev_why"])

    def with_parent_runs(self, runs, count=None):
        gh = self.w.gh

        def read(args):
            if args == ["api", "repos/o/r/commits/" + SHA, "--jq", ".parents[0].sha"]:
                return PARENT
            if args[0] == "api" and f"/actions/runs?head_sha={PARENT}&" in args[1]:
                return json.dumps({"total_count": len(runs) if count is None else count, "workflow_runs": runs})
            return gh(args)

        self.w.gh = read
        self.merged()
        self.w.workflows[SHA] = [dict(wf("ci", "failure", wid=1), id=77)]

    def test_a_failure_that_was_already_on_the_parent_is_unproved_not_red(self):
        self.with_parent_runs([parent_run("timed_out", 2), parent_run("success", 1),
                               parent_run("success", 3, event="pull_request")])
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "unproved")
        self.assertIn("dev was already red at beef000", self.data()["dev_why"])
        self.assertFalse(any(c[:2] == ["run", "rerun"] for c in self.w.gh_calls))

    def test_a_failure_that_the_parent_did_not_have_is_still_red(self):
        self.assert_normal_rerun([parent_run("success", 1), parent_run("failure", 1, workflow_id=2)])

    def assert_normal_rerun(self, runs, count=None):
        self.with_parent_runs(runs, count)
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")
        self.assertEqual(self.w.reruns, [["run", "rerun", "77", "--failed", "-R", "o/r"]])

    def test_recovered_parent_oldest_first(self):
        self.assert_normal_rerun([parent_run("failure", 1), parent_run("success", 2)])

    def test_recovered_parent_newest_first(self):
        self.assert_normal_rerun([parent_run("success", 2), parent_run("failure", 1)])

    def test_recovered_parent_on_a_later_attempt(self):
        self.assert_normal_rerun([parent_run("success", 1, run_attempt=2), parent_run("failure", 1)])

    def test_non_dev_pushes_and_pull_requests_are_not_parent_evidence(self):
        self.assert_normal_rerun([parent_run("failure", 2, event="pull_request"),
                                  parent_run("failure", 3, head_branch="topic")])

    def test_conflicting_latest_parent_attempts_are_not_evidence(self):
        self.assert_normal_rerun([parent_run("failure", 1), parent_run("success", 1)])

    def test_unfinished_latest_parent_run_is_not_evidence(self):
        self.assert_normal_rerun([parent_run("failure", 1), parent_run(None, 2, status="in_progress")])

    def test_incomplete_parent_page_is_not_evidence(self):
        self.assert_normal_rerun([parent_run("failure", 1)], count=101)

    def test_a_first_failed_push_run_is_run_again_and_not_red(self):
        self.merged()
        self.w.workflows[SHA] = [dict(wf("Factory tools", "failure", wid=2), id=77)]
        self.tick()
        self.assertIn(["run", "rerun", "77", "--failed", "-R", "o/r"], self.w.gh_calls)
        self.assertNotEqual(self.data().get("dev_result"), "red")
        self.assertNotIn("dev_result", self.data())
        self.assertIs(self.data().get("dev_rerun"), True)
        reasons = [r[0] for r in self.w.rows("SELECT reason FROM transitions WHERE job='5' ORDER BY id")]
        self.assertIn("dev rerun of the failed runs at feedfac", reasons)

    def test_a_push_run_that_fails_again_after_the_rerun_is_red(self):
        self.merged()
        self.w.workflows[SHA] = [dict(wf("Factory tools", "failure", wid=2), id=77)]
        self.tick()
        self.tick()
        reruns = [c for c in self.w.gh_calls if c[:2] == ["run", "rerun"]]
        self.assertEqual(reruns, [["run", "rerun", "77", "--failed", "-R", "o/r"]])
        self.assertEqual(self.data()["dev_result"], "red")
        self.assertIn("Factory tools", self.data()["dev_why"])

    def test_a_rerun_error_is_logged_and_does_not_stop_other_reruns(self):
        self.merged()
        self.w.workflows[SHA] = [
            dict(wf("ci", "success", wid=1), id=70),
            dict(wf("Factory tools", "failure", wid=2), id=77),
            dict(wf("Images", "timed_out", wid=3), id=78),
        ]
        real_gh = self.w.gh

        def gh(args):
            a = list(args)
            if a[:3] == ["run", "rerun", "77"]:
                self.w.gh_calls.append(a)
                raise D.Error("gh run rerun failed: exit 1: cannot rerun")
            return real_gh(a)

        self.w.gh = gh
        self.d.gh = gh
        self.tick()
        reruns = [c for c in self.w.gh_calls if c[:2] == ["run", "rerun"]]
        self.assertEqual(reruns, [
            ["run", "rerun", "77", "--failed", "-R", "o/r"],
            ["run", "rerun", "78", "--failed", "-R", "o/r"],
        ])
        self.assertIs(self.data().get("dev_rerun"), True)
        self.assertNotIn("dev_result", self.data())
        self.assertIn("#5", self.out.getvalue())
        self.assertIn("cannot rerun", self.out.getvalue())

    def test_a_cancelled_push_run_is_unproved_and_not_green(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "cancelled", wid=1)]
        self.tick(2)
        self.assertEqual(self.data()["dev_result"], "unproved")

    def test_no_run_at_all_is_unproved_after_the_checks_timeout(self):
        self.merged()
        self.tick(2)
        self.assertNotIn("dev_result", self.data())
        self.w.clock += 3601
        self.tick()
        self.assertEqual(self.data()["dev_result"], "unproved")

    def test_a_red_result_turns_green_when_the_failed_run_is_run_again(self):
        self.merged()
        self.w.workflows[SHA] = [wf("Factory tools", "failure", wid=2)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")
        self.w.workflows[SHA] = [wf("Factory tools", "success", wid=2)]
        self.tick()
        self.assertEqual(self.data()["dev_result"], "green")

    def test_a_green_result_is_not_asked_again(self):
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "success")]
        self.tick(2)
        self.assertEqual(self.data()["dev_result"], "green")
        before = len(self.push_reads())
        self.tick(3)
        self.assertEqual(len(self.push_reads()), before)

    def test_a_merge_the_dispatcher_did_not_make_is_not_asked(self):
        self.to_review()
        self.w.pr_state = "MERGED"
        self.tick(7)
        self.assertEqual(self.state(), "merged")
        self.assertEqual(self.commit_reads(), [])
        self.assertNotIn("own_merge", self.data())


class DevHeals(Base):
    LATER = "cafebabe87654321"
    merged, data = DevResult.merged, DevResult.data

    def later_dev(self, conclusion, status="ahead"):
        self.w.branches["dev"] = self.LATER
        self.w.workflows[self.LATER] = [wf("ci", conclusion, wid=7)]
        gh = self.w.gh

        def compare(args):
            a = list(args)
            if a[0] == "api" and "/compare/%s...%s" % (SHA, self.LATER) in a[1]:
                return json.dumps({"status": status})
            return gh(a)
        self.w.gh = compare

    def test_a_red_merge_is_green_once_a_later_dev_commit_passes(self):
        self.later_dev("success")
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=7)]
        self.tick(2)
        self.assertEqual(self.data()["dev_result"], "green")
        self.assertEqual(self.data()["dev_healed_by"], self.LATER)
        self.assertIn("cafebab", self.data()["dev_why"])

    def test_a_red_merge_stays_red_while_the_later_dev_commit_fails(self):
        self.later_dev("failure")
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=1)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")

    def test_a_later_commit_that_did_not_rerun_the_failed_workflow_does_not_heal_it(self):
        self.later_dev("success")
        self.merged()
        self.w.workflows[SHA] = [wf("Factory tools", "failure", wid=2), wf("ci", "success", wid=7)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")

    def test_a_later_commit_that_does_not_contain_the_merge_does_not_heal_it(self):
        self.later_dev("success", status="diverged")
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=1)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")

    def test_dev_healed_requires_cancelled_workflow_on_merge_sha_to_pass_on_head(self):
        self.later_dev("success")
        self.w.workflows[self.LATER] = [wf("ci", "success", wid=1)]
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=1), wf("Images", "cancelled", wid=2)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")
        self.w.workflows[self.LATER] = [wf("ci", "success", wid=1), wf("Images", "success", wid=2)]
        self.tick()
        self.assertEqual(self.data()["dev_result"], "green")

    def test_dev_healed_requires_startup_failure_workflow_on_merge_sha_to_pass_on_head(self):
        self.later_dev("success")
        self.w.workflows[self.LATER] = [wf("ci", "success", wid=1)]
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=1), wf("Images", "startup_failure", wid=2)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")

    def test_skipped_workflow_on_head_does_not_heal_unproven_workflow_on_merge_sha(self):
        self.later_dev("success")
        self.w.workflows[self.LATER] = [wf("ci", "success", wid=1), wf("Images", "skipped", wid=2)]
        self.merged()
        self.w.workflows[SHA] = [wf("ci", "failure", wid=1), wf("Images", "cancelled", wid=2)]
        self.tick(3)
        self.assertEqual(self.data()["dev_result"], "red")


if __name__ == "__main__":
    unittest.main()
