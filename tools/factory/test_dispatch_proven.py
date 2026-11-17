import unittest

from test_dispatch import Base, HEAD, ready, wf
import planning
import states


def proven(branch="plan/5"):
    return ready("**Proven branch**: %s" % branch)


class ProvenTest(Base):
    def setUp(self):
        super().setUp()
        self.w.issues = [{"number": 5, "title": "Fix x", "body": proven(), "comments": [], "labels": []}]
        self.w.branches = {"plan/5": "sha5aaaaaaaaaaa"}
        self.w.compare_files = ["a/b.py"]

    def creates(self):
        return [c for c in self.w.gh_calls if c[:2] == ["pr", "create"]]

    def test_a_proven_job_starts_no_build_run_and_gets_a_pull_request_from_its_branch(self):
        self.tick()
        self.assertEqual(self.w.sends, [])
        self.assertEqual(self.state(), "review_wait")
        job = self.d.store.get_job("5")
        self.assertEqual((job["pr"], job["proven"]), (42, "sha5aaaaaaaaaaa"))
        self.assertIn(["api", "-X", "POST", "repos/o/r/git/refs", "-f", "ref=refs/heads/chunk/5-p", "-f", "sha=sha5aaaaaaaaaaa"], self.w.gh_calls)
        creates = self.creates()
        self.assertEqual(len(creates), 1)
        c = creates[0]
        self.assertEqual(c[c.index("--base") + 1], "dev")
        self.assertEqual(c[c.index("--head") + 1], "chunk/5-p")
        self.assertEqual(c[c.index("--title") + 1], "Fix x")
        body = c[c.index("--body") + 1]
        self.assertTrue(body.startswith("Job: o/r#5, chunk p\n\n"))
        self.assertIn("plan/5", body)
        for heading in ("## Done", "## Evidence", "## Not changed", "## Unsure", "## Open", "## Next owner and their done-test"):
            self.assertIn(heading, body)

    def test_the_proven_job_goes_through_review_checks_and_proof_and_merges(self):
        self.tick(2)
        self.assertEqual(len(self.w.sends), 1)
        agent, msg, _ = self.w.sends[0]
        self.assertEqual(agent, "r1")
        self.assertIn("pull request #42 of rerun, for job #5", msg)
        self.w.finish("r1", "ok\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "checks")
        self.w.workflows[HEAD] = [wf("ci", "success"), wf("docs", "skipped", wid=2), wf("ci", "cancelled")]
        self.tick(3)
        self.assertEqual(self.w.merges, [["pr", "merge", "42", "-R", "o/r", "--merge", "--match-head-commit", HEAD, "--delete-branch"]])
        self.assertEqual(self.state(), "merged")
        self.assertEqual(len(self.w.sends), 1)

    def test_a_fix_round_of_a_proven_job_goes_to_a_free_builder_told_where_the_branch_is(self):
        self.tick(2)
        self.w.finish("r1", "no\nVERDICT: REJECT @abcdef1: the test does not pin the change")
        self.tick()
        self.assertEqual(self.state(), "fix_wait")
        self.tick()
        agent, msg, _ = self.w.sends[-1]
        self.assertIn(agent, ("b1", "b2"))
        self.assertIn("wt new rerun 5 p", msg)
        self.assertIn("git reset --hard origin/chunk/5-p", msg)
        self.assertEqual(self.state(), "fixing")
        self.assertEqual(self.d.store.get_job("5")["builder"], agent)

    def test_a_proven_branch_that_is_not_plan_of_the_issue_returns_the_job_to_the_planner(self):
        self.w.issues[0]["body"] = proven("plan/9")
        self.w.branches["plan/9"] = "sha9aaaaaaaaaaa"
        self.tick()
        self.assertEqual(self.state(), "returned")
        self.assertEqual(self.w.sends, [])
        self.assertIn("plan: **Proven branch** names plan/9, not plan/5", self.out.getvalue())

    def test_a_missing_proven_branch_returns_the_job_to_the_planner(self):
        self.w.branches = {}
        self.tick()
        self.assertEqual(self.state(), "returned")
        self.assertEqual(self.w.sends, [])
        self.assertIn("plan: the proven branch plan/5 is not on GitHub", self.out.getvalue())

    def test_a_proven_branch_with_a_file_outside_files_returns_the_job(self):
        self.w.compare_files = ["a/b.py", "c/d.py"]
        self.tick()
        self.assertEqual(self.state(), "returned")
        self.assertEqual(self.w.sends, [])
        self.assertIn("c/d.py", self.out.getvalue())
        self.assertEqual(self.creates(), [])

    def test_a_job_without_the_line_is_built_as_today(self):
        self.w.issues[0]["body"] = ready()
        self.tick()
        self.assertEqual(self.state(), "building")
        self.assertEqual(self.w.sends[0][0], "b1")

    def test_a_queued_job_may_move_to_review_wait(self):
        self.assertTrue(states.allowed("queued", "review_wait"))

    def test_the_planner_brief_says_to_keep_the_proven_change_as_a_branch(self):
        text = planning.brief({"number": 612, "title": "Floor", "body": ""}, "o/rerun")
        self.assertIn("push that change as `plan/<child>`", text)
        self.assertIn("**Proven branch**: plan/<child>", text)


if __name__ == "__main__":
    unittest.main()
