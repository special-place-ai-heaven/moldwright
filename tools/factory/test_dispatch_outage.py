import unittest.mock
import dispatch as D
from test_dispatch import Base, World, ready


class Outage(Base):
    def setUp(self):
        super().setUp()
        self.w = World(issues=[{"number": 5, "title": "Fix x", "body": ready(), "comments": []},
                               {"number": 6, "title": "Fix y", "body": ready(), "comments": []}])
        self.w.ledger = self.cfg["ledger_file"]

    def test_a_pass_where_every_job_fails_counts_for_no_job(self):
        self.tick()

        def boom(d, j):
            raise RuntimeError("shared fault")
        with unittest.mock.patch.object(D.Dispatcher, "step", boom):
            self.tick(25)
            self.w.clock += D.FAIL_AFTER_S
            self.tick()
        self.assertNotEqual(self.state(5), "failed")
        self.assertNotEqual(self.state(6), "failed")
        self.assertEqual([j.get("errors", 0) for j in self.d.jobs()], [0, 0])
        self.assertIn("pass outage: 2 jobs failed, counters kept", self.out.getvalue())

    def test_one_failing_job_among_clean_ones_still_ends_after_20(self):
        self.tick()
        real = D.Dispatcher.step

        def one_broken(d, j):
            if j["issue"] == 5:
                raise RuntimeError("only this job")
            return real(d, j)
        with unittest.mock.patch.object(D.Dispatcher, "step", one_broken):
            self.tick(19)
            self.w.clock += D.FAIL_AFTER_S
            self.tick()
        self.assertEqual(self.state(5), "failed")
        self.assertNotEqual(self.state(6), "failed")
        self.assertNotIn("pass outage", self.out.getvalue())
