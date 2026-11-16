import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog
import store as S


def ev(job, group="a"):
    return {"job": job, "group": group}


def run(job, started, ended):
    return {"job": job, "started": started, "ended": ended}


class TestChangelog(unittest.TestCase):
    def test_rate_is_events_of_the_group_per_twenty_jobs(self):
        jobs = list(range(20))
        events = [ev(0), ev(1), ev(2), ev(3, "b"), ev(99)]
        self.assertEqual(changelog.rate(events, jobs, "a"), 3.0)
        self.assertEqual(changelog.rate([ev(0)], list(range(10)), "a"), 2.0)
        self.assertIsNone(changelog.rate(events, [], "a"))

    def test_before_takes_the_last_twenty_jobs_ended_by_then(self):
        ended = [run(i, i * 10, i * 10 + 5) for i in range(1, 31)]
        self.assertEqual(changelog.before(ended, 305), list(range(11, 31)))
        self.assertEqual(changelog.before(ended, 205), list(range(1, 21)))
        self.assertEqual(changelog.before(ended, 55), [1, 2, 3, 4, 5])
        self.assertEqual(changelog.before(ended, 4), [])

    def test_after_needs_twenty_jobs_started_and_ended_since_the_change_went_live(self):
        ended = [run(i, i * 10, i * 10 + 5) for i in range(1, 41)]
        self.assertIsNone(changelog.after(ended, 100, 100 + 19 * 10 + 5 - 10))
        self.assertEqual(changelog.after(ended, 100, 1000), list(range(10, 30)))
        self.assertIsNone(changelog.after(ended, 100, 290))
        self.assertEqual(changelog.after(ended, 101, 1000), list(range(11, 31)))

    def test_only_a_lower_rate_keeps_the_change(self):
        self.assertEqual(changelog.verdict(3.0, 2.0), "kept")
        self.assertEqual(changelog.verdict(3.0, 3.0), "revert")
        self.assertEqual(changelog.verdict(0.0, 0.0), "revert")
        self.assertEqual(changelog.verdict(2.0, 3.0), "revert")
        self.assertEqual(changelog.verdict(None, 1.0), "revert")
        self.assertEqual(changelog.verdict(3.0, None), "revert")


class TestChanges(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.s = S.Store(os.path.join(self.d.name, "ledger.db"))

    def tearDown(self):
        self.s.close()
        self.d.cleanup()

    def test_a_change_is_a_row_with_its_group_and_rate_before(self):
        cid = self.s.add_change(1078, "stall", "repo", 4.0, at="2026-11-16T10:00:00Z")
        self.assertEqual(self.s.changes(), [{
            "id": cid, "at": "2026-11-16T10:00:00Z", "issue": 1078, "grp": "stall",
            "kind": "repo", "before": 4.0, "live_at": None, "after": None,
            "verdict": None, "revert": None, "told": 0}])

    def test_the_rate_after_the_verdict_and_the_revert_issue_are_written_later(self):
        first = self.s.add_change(1, "g", "instructions", None)
        second = self.s.add_change(2, "g", "repo", 1.0)
        self.s.set_change(first, live_at=100.0, after=2.0, verdict="revert", revert=77, told=1)
        rows = self.s.changes()
        self.assertEqual([r["id"] for r in rows], [first, second])
        self.assertEqual(rows[0]["live_at"], 100.0)
        self.assertEqual(rows[0]["after"], 2.0)
        self.assertEqual(rows[0]["verdict"], "revert")
        self.assertEqual(rows[0]["revert"], 77)
        self.assertEqual(rows[0]["told"], 1)
        self.assertIsNone(rows[1]["verdict"])

    def test_an_unknown_column_is_refused(self):
        cid = self.s.add_change(1, "g", "repo", 1.0)
        with self.assertRaises(ValueError):
            self.s.set_change(cid, grp="other")
        with self.assertRaises(ValueError):
            self.s.set_change(cid, after=1.0, bogus=1)
        self.assertIsNone(self.s.changes()[0]["after"])


if __name__ == "__main__":
    unittest.main()
