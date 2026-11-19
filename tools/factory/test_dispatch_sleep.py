import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_dispatch as T
import test_dispatch_toolcalls as TC

D = T.D
WAITS = "the dispatcher waits for them"
COUNTS = "counts every build or fix run with a sleep as a failure"
REFUSED = "BLOCKED: TRANSIENT: ci run of the head not finished"
FAILS = "SELECT kind, station, job, reason FROM failures"


class Briefs(unittest.TestCase):
    def test_every_build_and_fix_brief_says_who_waits_and_that_a_sleep_counts(self):
        j = {"issue": 7, "title": "Fix x"}
        briefs = [D.build_brief(j), D.fix_brief(j, 3, "r"), D.senior_brief(j, 3, "r")]
        for text in briefs:
            for part in (WAITS, COUNTS, REFUSED):
                self.assertIn(part, text)
            self.assertNotIn("\\`", text)
        for text in briefs[1:]:
            self.assertIn("/data/tools/bin/packet rerun 3", text)
            self.assertIn("worktree:", text)
        proven = D.fix_brief(dict(j, proven="abc"), 3, "r")
        self.assertIn(WAITS, proven)
        self.assertNotIn("/data/tools/bin/packet", proven)


class Slept(T.Base):
    def build_with(self, calls):
        self.w.finish("b1", T.PR_LINE)
        rid = [r for r, a in self.w.order if a == "b1"][-1]
        self.w.runs[rid]["toolCalls"] = calls
        return rid

    def test_a_slept_build_run_is_one_failure(self):
        self.tick()
        self.build_with(TC.CALLS)
        self.tick(3)
        self.assertEqual(self.w.rows(FAILS), [("sleep in build run", "build", "5", "1 of 4 shell calls slept")])
        self.tick(3)
        self.assertEqual(len(self.w.rows(FAILS)), 1)

    def test_a_run_sent_before_the_change_is_no_failure(self):
        self.tick()
        self.d.store.set("-", "sleep_since", "2999-01-01T00:00:00Z")
        rid = self.build_with(TC.CALLS)
        self.tick(3)
        self.assertEqual(self.w.rows("SELECT tools_read FROM fires WHERE run_id=?", rid), [("ok",)])
        self.assertEqual(self.w.rows(FAILS), [])

    def test_a_sleep_row_never_stands_for_the_real_reason(self):
        self.tick()
        self.d.store.add_failure("blocked", "7", station="build", reason="REAL build reason")
        self.d.store.add_failure(D.SLEEP_KIND, "7", station="build", reason="1 of 4 shell calls slept")
        text = self.d.verdict({"issue": 7, "reason": "x"})
        self.assertIn("- build: REAL build reason", text)
        self.assertNotIn("slept", text)


class Hold(T.Base):
    def rejected(self):
        self.to_review()
        self.w.workflows[T.HEAD] = [T.wf("ci", None, status="in_progress")]
        self.w.finish("r1", "VERDICT: REJECT @abcdef1: wrong sum")

    def rounds(self):
        return len([s for s in self.w.sends if "One fix round" in s[1]])

    def test_a_fix_round_waits_for_the_run_of_the_head(self):
        self.rejected()
        self.tick(3)
        self.assertEqual((self.state(), self.rounds()), ("fix_wait", 0))
        self.w.workflows[T.HEAD] = [T.wf("ci", "success")]
        self.tick(2)
        self.assertEqual((self.state(), self.rounds()), ("fixing", 1))

    def test_the_hold_ends_after_its_limit(self):
        self.rejected()
        self.tick(2)
        self.w.clock += D.FIX_HOLD_S + 1
        self.tick(2)
        self.assertEqual((self.state(), self.rounds()), ("fixing", 1))

    def test_a_refused_push_goes_back_to_the_queue(self):
        self.to_review()
        self.w.finish("r1", "VERDICT: REJECT @abcdef1: wrong sum")
        self.tick(2)
        self.w.finish("b1", REFUSED)
        self.tick(2)
        self.assertEqual(self.state(), "fix_wait")


if __name__ == "__main__":
    unittest.main()
