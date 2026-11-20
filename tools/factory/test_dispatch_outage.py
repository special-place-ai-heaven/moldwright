import unittest
import unittest.mock
import dispatch as D
from test_dispatch import Base, World, ready


class Outage(Base):
    def setUp(self):
        super().setUp()
        self.w = World([{"number": 5, "title": "Fix x", "body": ready(), "comments": []},
                        {"number": 6, "title": "Fix y", "body": ready(), "comments": []}])
        self.w.ledger = self.cfg["ledger_file"]

    def counters(self):
        return {j["issue"]: j.get("errors", 0) for j in self.d.jobs()}

    def test_a_pass_where_every_job_fails_counts_for_no_job(self):
        self.tick()
        self.w.runs.clear()
        self.tick(25)
        self.w.clock += D.FAIL_AFTER_S
        self.tick()
        self.assertEqual(self.counters(), {5: 0, 6: 0})
        self.assertNotIn("failed", [j["state"] for j in self.d.jobs()])

    def test_one_failing_job_among_clean_ones_still_ends_after_20(self):
        real = D.Dispatcher.step

        def step(disp, j):
            if j["issue"] == 5:
                raise D.Error("read failed")
            return real(disp, j)

        with unittest.mock.patch.object(D.Dispatcher, "step", step):
            self.tick(19)
            self.w.clock += D.FAIL_AFTER_S
            self.tick()
        self.assertEqual(self.state(5), "failed")
