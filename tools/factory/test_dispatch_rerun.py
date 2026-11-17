import unittest

from test_dispatch import Base, HEAD, wf


class FirstFailedCheckRerun(Base):
    def failures(self):
        return [tuple(r) for r in self.w.rows("SELECT kind, station, reason FROM failures ORDER BY id")]

    def test_the_first_failed_check_of_a_head_runs_its_failed_jobs_again_and_asks_no_builder(self):
        self.to_checks()
        self.w.workflows[HEAD] = [dict(wf("ci", "failure", wid=1), id=77)]
        sends = len(self.w.sends)
        self.tick()
        self.assertEqual(self.w.reruns, [["run", "rerun", "77", "-R", "o/r", "--failed"]])
        self.assertEqual(self.state(), "checks")
        self.assertEqual(len(self.w.sends), sends)

    def test_green_after_the_re_run_merges_and_is_kept_as_a_flaky_check(self):
        self.to_checks()
        self.w.workflows[HEAD] = [dict(wf("ci", "failure", wid=1), id=77)]
        self.tick()
        self.w.workflows[HEAD] = [dict(wf("ci", "success", wid=1), id=77)]
        self.tick()
        self.assertEqual(self.state(), "merged")
        flaky = [f for f in self.failures() if f[0] == "flaky check"]
        self.assertEqual([(kind, station) for kind, station, _ in flaky], [("flaky check", "checks")])
        self.assertIn("ci", flaky[0][2])

    def test_a_second_failure_of_the_same_head_goes_to_the_builder_once(self):
        self.to_checks()
        self.w.workflows[HEAD] = [dict(wf("ci", "failure", wid=1), id=77)]
        self.tick(3)
        self.assertEqual(len(self.w.reruns), 1)
        self.assertEqual(self.state(), "fixing")
        self.assertIn(("ci red after push", "build"), [(k, s) for k, s, _ in self.failures()])

    def test_only_the_latest_run_of_each_workflow_is_run_again(self):
        self.to_checks()
        self.w.workflows[HEAD] = [
            dict(wf("lint", "failure", wid=1), id=71),
            dict(wf("image", "failure", wid=2), id=77),
            dict(wf("image", "failure", wid=2), id=79)]
        self.tick()
        self.assertEqual(self.w.reruns, [["run", "rerun", "71", "-R", "o/r", "--failed"],
                                         ["run", "rerun", "79", "-R", "o/r", "--failed"]])

    def test_the_wait_after_the_re_run_starts_the_checks_clock_again(self):
        self.to_checks()
        self.w.workflows[HEAD] = [dict(wf("ci", "failure", wid=1), id=77)]
        self.w.clock += 40 * 60
        self.tick()
        self.w.clock += 40 * 60
        self.w.workflows[HEAD] = [dict(wf("ci", None, status="in_progress", wid=1), id=77)]
        self.tick()
        self.assertEqual(self.state(), "checks")


if __name__ == "__main__":
    unittest.main()
