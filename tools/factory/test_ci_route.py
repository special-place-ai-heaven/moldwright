import json, os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_route
from test_dispatch import Base

LIGHT = json.dumps(ci_route.POOL["light"])
HEAVY = json.dumps(ci_route.POOL["heavy"])
HOSTED = json.dumps("ubuntu-latest")


def runner(label, busy=False, status="online"):
    return {"status": status, "busy": busy, "labels": [{"name": "self-hosted"}, {"name": "Linux"}, {"name": label}]}


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Choose(unittest.TestCase):
    def test_light_work_goes_to_an_idle_light_runner_else_github(self):
        self.assertEqual(ci_route.choose([runner("light")], False)["light"], LIGHT)
        self.assertEqual(ci_route.choose([runner("light", busy=True), runner("light", status="offline")], False)["light"], HOSTED)

    def test_tests_stay_on_github_until_github_makes_them_wait(self):
        self.assertEqual(ci_route.choose([runner("heavy")], False)["heavy"], HOSTED)
        self.assertEqual(ci_route.choose([runner("heavy")], True)["heavy"], HEAVY)
        self.assertEqual(ci_route.choose([runner("heavy", busy=True)], True)["heavy"], HOSTED)

    def test_github_waits_only_when_a_queued_run_is_older_than_the_limit(self):
        now = 10000.0
        self.assertTrue(ci_route.hosted_waiting([{"created_at": stamp(now - 30)}], now))
        self.assertFalse(ci_route.hosted_waiting([{"created_at": stamp(now - 5)}], now))
        self.assertFalse(ci_route.hosted_waiting([], now))


class Beat(Base):
    def setUp(self):
        super().setUp()
        self.cfg["ci_route_org"] = "o"
        self.w.runners = [runner("light"), runner("heavy")]

    def test_the_beat_sets_each_variable_once_and_again_only_when_it_changes(self):
        self.tick()
        self.assertEqual(self.w.variables, {"CI_RUNS_ON_LIGHT": LIGHT, "CI_RUNS_ON_HEAVY": HOSTED})
        sets = lambda: [c for c in self.w.gh_calls if c[:2] == ["variable", "set"]]
        self.assertEqual(len(sets()), 2)
        self.tick()
        self.assertEqual(len(sets()), 2)
        self.w.runners = [runner("light", busy=True), runner("heavy")]
        self.w.queued_runs = [{"created_at": stamp(self.w.clock - 60)}]
        self.tick()
        self.assertEqual(self.w.variables, {"CI_RUNS_ON_LIGHT": HOSTED, "CI_RUNS_ON_HEAVY": HEAVY})
        self.assertEqual(len(sets()), 4)
        self.assertIn("CI heavy now runs on the pool", self.out.getvalue())

    def test_without_the_setting_the_beat_reads_no_runners(self):
        del self.cfg["ci_route_org"]
        self.tick()
        self.assertEqual([c for c in self.w.gh_calls if "/actions/runners" in " ".join(c)], [])


if __name__ == "__main__":
    unittest.main()
