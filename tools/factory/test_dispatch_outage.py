import unittest.mock

import dispatch as D
from test_dispatch import Base, World, ready


class Outage(Base):
    def setUp(self):
        super().setUp()
        self.w = World(issues=[
            {"number": 5, "title": "Fix x", "body": ready(), "comments": []},
            {"number": 6, "title": "Fix y", "body": ready(), "comments": []},
        ])
        self.w.ledger = self.cfg["ledger_file"]

    def counters(self):
        return {j["issue"]: j for j in self.d.store.jobs()}

    def test_a_pass_where_every_job_fails_counts_for_no_job(self):
        self.tick()
        with unittest.mock.patch.object(D.Dispatcher, "step", side_effect=RuntimeError("down")):
            self.tick(25)
            self.w.clock += D.FAIL_AFTER_S
            self.tick()
        jobs = self.counters()
        for n in (5, 6):
            self.assertNotEqual(jobs[n]["state"], "failed")
            self.assertEqual(jobs[n].get("errors", 0), 0)
            self.assertNotIn("failing_since", jobs[n])
            self.assertNotIn("last_error", jobs[n])
        self.assertIn("pass outage: 2 jobs failed, counters kept", self.out.getvalue())

    def test_one_failing_job_among_clean_ones_still_ends_after_20(self):
        self.tick()

        def step(d, j):
            if j["issue"] == 5:
                raise RuntimeError("broken")

        with unittest.mock.patch.object(D.Dispatcher, "step", autospec=True, side_effect=step):
            self.tick(19)
            self.w.clock += D.FAIL_AFTER_S
            self.tick()
        self.assertEqual(self.state(5), "failed")
        self.assertEqual(self.state(6), "building")
