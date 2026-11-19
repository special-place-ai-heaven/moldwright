import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planning
import test_planning_start as T
from test_planning_pick import issue


class TokensFirst(unittest.TestCase):
    def test_parked_issues_are_not_planned(self):
        got = planning.unplanned([issue(1, ["P0", "factory-paused"], "2026-11-01"), issue(2, ["P3"], "2026-11-02")])
        self.assertEqual([i["number"] for i in got], [2])

    def test_token_work_is_planned_before_any_other(self):
        got = planning.unplanned([issue(1, ["P0"], "2026-11-01"), issue(2, ["P2", planning.TOKENS], "2026-11-03"),
                                  issue(3, ["P1", planning.TOKENS], "2026-11-04"), issue(4, ["P1"], "2026-10-01")])
        self.assertEqual([i["number"] for i in got], [3, 2, 1, 4])

    def test_token_work_still_needs_a_priority(self):
        self.assertEqual(planning.unplanned([issue(1, [planning.TOKENS], "2026-11-01")]), [])

    def test_the_backlog_read_covers_more_than_a_hundred_issues(self):
        r = T.Rig()
        r.station.once(1)
        listed = r.listed()[0]
        self.assertEqual(listed[listed.index("--limit") + 1], "1000")


if __name__ == "__main__":
    unittest.main()
