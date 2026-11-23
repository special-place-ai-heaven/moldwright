import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dispatch import Base, D, HEAD, wf

SHA = "feedface12345678"


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

    def test_a_first_failed_push_run_is_run_again_and_not_red(self):
        self.merged()
        self.w.workflows[SHA] = [dict(wf("ci", "success", wid=1), id=101),
                                 dict(wf("Factory tools", "failure", wid=2), id=202),
                                 dict(wf("Images", "timed_out", wid=3), id=303)]
        self.tick()
        self.assertIn(["run", "rerun", "202", "--failed", "-R", "o/r"], self.w.gh_calls)
        self.assertIn(["run", "rerun", "303", "--failed", "-R", "o/r"], self.w.gh_calls)
        self.assertNotIn(["run", "rerun", "101", "--failed", "-R", "o/r"], self.w.gh_calls)
        self.assertNotEqual(self.data().get("dev_result"), "red")
        self.assertNotIn("dev_result", self.data())
        self.assertTrue(self.data()["dev_rerun"])
        reasons = [r[0] for r in self.w.rows("SELECT reason FROM transitions WHERE job='5' ORDER BY id")]
        self.assertIn("dev rerun of the failed runs at feedfac", reasons)

    def test_a_push_run_that_fails_again_after_the_rerun_is_red(self):
        self.merged()
        self.w.workflows[SHA] = [dict(wf("Factory tools", "failure", wid=2), id=202)]
        self.tick()
        reruns = [c for c in self.w.gh_calls if c[:2] == ["run", "rerun"]]
        self.assertEqual(reruns, [["run", "rerun", "202", "--failed", "-R", "o/r"]])
        self.tick()
        self.assertEqual(self.data()["dev_result"], "red")
        self.assertIn("Factory tools", self.data()["dev_why"])
        self.assertEqual([c for c in self.w.gh_calls if c[:2] == ["run", "rerun"]], reruns)

    def test_a_rerun_error_is_logged_and_does_not_stop_other_reruns(self):
        self.merged()
        self.w.workflows[SHA] = [dict(wf("ci", "failure", wid=1), id=101),
                                 dict(wf("Factory tools", "timed_out", wid=2), id=202)]
        real_gh = self.w.gh

        def gh(args):
            a = list(args)
            if a == ["run", "rerun", "101", "--failed", "-R", "o/r"]:
                self.w.gh_calls.append(a)
                raise D.Error("gh run rerun failed: exit 1: cannot rerun")
            return real_gh(a)

        self.w.gh = self.d.gh = gh
        self.tick()
        self.assertIn(["run", "rerun", "202", "--failed", "-R", "o/r"], self.w.gh_calls)
        self.assertTrue(self.data()["dev_rerun"])
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
