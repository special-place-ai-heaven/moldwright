import contextlib, io, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ceilings
import clocks
import dispatch as D
import store as ledger_store
import timeline
from test_dispatch import World, PR_LINE, ready

RATE = {"status": "error", "error": "429 Too Many Requests"}


def mk(n, worker="coder", folder="a/"):
    return {"number": n, "title": "T%d" % n, "comments": [],
            "body": ready().replace("**Worker**: coder", "**Worker**: " + worker).replace("a/", "%s%d/" % (folder.rstrip("/"), n))}


def cw(i, runs=1, name=None):
    return {"id": i, "name": name or i.upper(), "runs": runs}


class Ceilings(unittest.TestCase):
    def world(self, types, issues):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = World(issues)
        cfg = {"repo": "o/r", "label": "factory", "checks_timeout_s": 3600, "auto_plan_marker": True, "types": types,
               "ledger_file": os.path.join(tmp.name, "ledger.db"), "json_state_file": os.path.join(tmp.name, "dispatch.json"),
               "heartbeat_file": os.path.join(tmp.name, "heartbeat")}
        self.w.ledger = cfg["ledger_file"]
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out):
            self.d = D.Dispatcher(cfg, self.w.account, self.w.gh, now=lambda: self.w.clock)
        self.addCleanup(self.d.close)
        return self.d

    def beat(self, n=1):
        with contextlib.redirect_stdout(self.out):
            for _ in range(n):
                self.d.once()

    def who(self):
        return [s[0] for s in self.w.sends]

    def coders(self, runs, n):
        return self.world({"coder": {"max_jobs": 8, "coworkers": [cw("c1", runs)]}, "reviewer": {"coworkers": [cw("r1")]}},
                          [mk(k) for k in range(1, n + 1)])

    def test_a_rate_limit_halves_the_ceiling_of_its_pool_for_the_hold(self):
        self.coders(3, 4)
        self.beat()
        self.assertEqual(len(self.w.sends), 3)
        self.w.runs["run1"] = dict(RATE)
        self.beat()
        self.assertEqual(len(self.w.sends), 3)
        self.assertEqual(ceilings.cap(self.d.store, "coder", self.w.clock), 1)
        self.assertIn("rate limit on coder: at most 1 at once until 1970-01-01T00:31:40Z", self.out.getvalue())
        lines = timeline.status_lines(timeline.read_rows(self.w.ledger), self.w.clock)
        self.assertIn("ceiling of coder lowered to 1 at once until 00:31 UTC (rate limit)", lines)
        self.w.clock += 61
        self.beat()
        self.assertEqual(len(self.w.sends), 3)
        self.w.clock += ceilings.HOLD_S
        self.beat()
        self.assertEqual(len(self.w.sends), 4)
        lines = timeline.status_lines(timeline.read_rows(self.w.ledger), self.w.clock)
        self.assertEqual([x for x in lines if x.startswith("ceiling of")], [])

    def test_only_rate_limits_and_overloads_count(self):
        got = [clocks.rate_limited(e) for e in ("provider_overloaded", "429 Too Many Requests", "sign-in renewed during the run",
                                                "403 attention required", "You hit your weekly limit")]
        self.assertEqual(got, [True, True, False, False, False])
        self.assertFalse(clocks.rate_limited(None))

    def test_two_rate_limits_in_one_beat_halve_from_the_active_cap_down_to_one(self):
        self.coders(3, 3)
        self.beat()
        now = self.w.clock
        self.assertEqual(ceilings.lower(self.d.store, "coder", 4, now), (2, now + ceilings.HOLD_S))
        self.w.runs["run1"] = dict(RATE)
        self.w.runs["run2"] = dict(RATE)
        self.beat()
        self.assertEqual(ceilings.cap(self.d.store, "coder", now), 1)
        self.assertEqual(ceilings.cap(self.d.store, "coder", now + ceilings.HOLD_S), None)

    def test_an_unreadable_ceiling_counts_as_none_and_is_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            st = ledger_store.Store(os.path.join(t, "l.db"))
            try:
                st.set("-", "ceiling:coder", "{bad")
                st.set("-", "ceiling:reviewer", '{"cap": "x", "until": 5000}')
                self.assertIsNone(ceilings.cap(st, "coder", 1000))
                self.assertEqual(timeline.read_rows(os.path.join(t, "l.db"))["ceilings"], [])
                self.assertEqual(ceilings.lower(st, "coder", 2, 1000), (1, 1000 + ceilings.HOLD_S))
                self.assertEqual(ceilings.cap(st, "coder", 1000), 1)
            finally:
                st.db.close()

    def test_a_rate_limit_on_a_security_review_lowers_the_security_pool(self):
        self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1")]}, "reviewer": {"coworkers": [cw("r1")]},
                    "security": {"max_jobs": 1, "role": "review", "coworkers": [cw("s1")]}}, [mk(5, "security")])
        self.beat()
        self.w.finish("b1", PR_LINE)
        self.beat(2)
        self.assertEqual(self.who(), ["b1", "s1"])
        self.w.runs["run2"] = dict(RATE)
        self.beat()
        self.assertEqual(ceilings.cap(self.d.store, "security", self.w.clock), 1)
        self.assertIsNone(ceilings.cap(self.d.store, "reviewer", self.w.clock))
        self.assertIsNone(ceilings.cap(self.d.store, "coder", self.w.clock))

    def test_a_fix_waits_on_the_build_pool_of_its_job_not_on_the_reviewer_pool(self):
        self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1", 2)]}, "reviewer": {"coworkers": [cw("r1")]},
                    "security": {"max_jobs": 1, "role": "review", "coworkers": [cw("s1")]}}, [mk(5), mk(6, "security")])
        self.beat()
        self.w.runs["run1"] = {"status": "done", "output": PR_LINE, "error": None}
        self.w.runs["run2"] = {"status": "done", "output": PR_LINE.replace("/42", "/43"), "error": None}
        self.beat(2)
        self.assertEqual(self.who(), ["b1", "b1", "r1", "s1"])
        ceilings.lower(self.d.store, "reviewer", 2, self.w.clock)
        self.w.finish("s1", "VERDICT: REJECT @abcdef1: the test is missing")
        self.beat(2)
        self.assertEqual(self.d.store.get_job("6")["state"], "fixing")
        self.assertEqual(self.who(), ["b1", "b1", "r1", "s1", "b1"])

    def test_one_coworker_in_two_pools_is_held_only_by_the_pool_of_the_run(self):
        self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1", 2)]}, "reviewer": {"coworkers": [cw("B", 3, "BRUCE")]},
                    "security": {"max_jobs": 1, "role": "review", "coworkers": [cw("B", 3, "BRUCE")]}}, [mk(5), mk(6, "security")])
        self.beat()
        self.w.runs["run1"] = {"status": "done", "output": PR_LINE, "error": None}
        self.beat(2)
        self.assertEqual(self.who(), ["b1", "b1", "B"])
        ceilings.lower(self.d.store, "security", 1, self.w.clock)
        self.w.runs["run2"] = {"status": "done", "output": PR_LINE.replace("/42", "/43"), "error": None}
        self.beat(2)
        self.assertEqual(self.who(), ["b1", "b1", "B", "B"])
        self.assertEqual(self.d.store.get_job("6")["pool"], "security")


if __name__ == "__main__":
    unittest.main()
