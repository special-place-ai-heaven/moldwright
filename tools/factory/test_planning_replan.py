import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planning
import test_planning_start as T


def rig(labels, state):
    T.BACKLOG[:] = [{"number": 12, "title": "T12", "labels": [{"name": n} for n in labels], "createdAt": "2026-11-05T00:00:00Z"}]
    r = T.Rig()
    for k, v in (("state", state), ("agent", T.P1), ("intent", "1970-01-01T00:00:00Z"), ("resent", '["plan"]'), ("run", "run9"), ("copy", "0"), ("started", T.STAMP)):
        r.store.set("plan:12", k, v)
    return r


class Replan(unittest.TestCase):
    def setUp(self):
        self.saved = list(T.BACKLOG)

    def tearDown(self):
        T.BACKLOG[:] = self.saved

    def test_finished_plan_is_not_sent_again_without_the_label(self):
        r = rig(["P0"], "blocked")
        r.station.once(1)
        self.assertEqual(r.sends, [])

    def test_the_label_plans_a_finished_issue_again(self):
        r = rig(["P0", planning.REPLAN, "factory-blocked"], "blocked")
        r.station.once(1)
        self.assertEqual(r.numbers(), [12])
        rec = r.store.get_all("plan:12")
        self.assertEqual((rec["state"], rec["resent"]), ("running", "[]"))
        self.assertIn(("12", "-" + planning.REPLAN), r.edits())
        self.assertIn(("12", "-factory-blocked"), r.edits())

    def test_the_label_leaves_a_running_plan_alone(self):
        r = rig(["P0", planning.REPLAN, "factory-plan"], "running")
        r.station.once(1)
        self.assertEqual(r.sends, [])
        self.assertEqual(r.store.get_all("plan:12")["state"], "running")


if __name__ == "__main__":
    unittest.main()
