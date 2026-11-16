import json
import time
import unittest

import escapes
from test_dispatch import Base, HEAD, wf

NOW = 1_800_000_000.0
DAY = 24 * 3600


def job(n, state="merged", merged_at=NOW - DAY, body=""):
    return {"issue": n, "state": state, "merged_at": merged_at, "body": body}


def dev_red(first_line, extra=""):
    return {"evidence": first_line + "\n" + extra}


class Pure(unittest.TestCase):
    def test_a_merged_issue_that_is_open_again_escaped(self):
        found = escapes.find([job(5)], {5, 7}, {}, NOW)
        self.assertEqual(found, [("5", "reopened")])

    def test_a_later_job_that_names_it_on_a_repairs_line_escaped(self):
        jobs = [job(5), job(9, state="queued", merged_at=None, body="Intro\n**Repairs**: #5, #5\n")]
        self.assertEqual(escapes.repairs(jobs[1]["body"]), [5])
        self.assertEqual(escapes.find(jobs, None, {}, NOW), [("5", "repair #9")])

    def test_a_number_elsewhere_in_a_body_is_no_repair(self):
        body = "Depends on: #5\nSee #5 and the running text about **Repairs**: #5\n"
        self.assertEqual(escapes.repairs(body), [])
        self.assertEqual(escapes.find([job(5), job(9, state="queued", merged_at=None, body=body)], None, {}, NOW), [])

    def test_a_problem_whose_key_names_the_job_escaped(self):
        problems = {"ci red #5": {"evidence": "anything"}, "ci red #7": {"evidence": "the job is #5 here"}}
        self.assertEqual(escapes.find([job(5)], None, problems, NOW), [("5", "problem ci red #5")])

    def test_dev_red_names_the_job_of_its_merge(self):
        problems = {"dev red": dev_red("main is red (job #5) at #7", "PR #5 went in")}
        self.assertEqual(escapes.find([job(5), job(7)], None, problems, NOW), [("5", "problem dev red")])
        other = {"dev red": dev_red("main is red (job #7) at #5")}
        self.assertEqual(escapes.find([job(5), job(7)], None, other, NOW), [("7", "problem dev red")])

    def test_after_seven_days_nothing_escapes(self):
        old = job(5, merged_at=NOW - escapes.WINDOW_S - 1)
        self.assertEqual(escapes.find([old], {5}, {"dev red": dev_red("x (job #5)")}, NOW), [])

    def test_a_job_that_is_not_merged_never_escapes(self):
        self.assertEqual(escapes.find([job(5, state="queued", merged_at=None)], {5}, {}, NOW), [])
        self.assertEqual(escapes.find([job(5, state="merged", merged_at=None)], {5}, {}, NOW), [])


class Dispatch(Base):
    def setUp(self):
        super().setUp()
        self.w.clock = time.time()

    def merged(self):
        self.to_checks()
        self.w.workflows[HEAD] = [wf("ci", "success")]
        self.tick()
        self.assertEqual(self.state(), "merged")

    def test_a_reopened_merged_issue_is_recorded_once_with_a_failure_event(self):
        self.merged()
        self.w.open_numbers.add(5)
        self.tick(25)
        self.assertEqual(sorted(self.d.store.get_all("escaped")), ["5|reopened"])
        self.assertEqual(json.loads(self.d.store.get_all("escaped")["5|reopened"])["by"], "reopened")
        rows = [f for f in self.d.store.failures() if f["kind"] == "escaped"]
        self.assertEqual([(r["job"], r["reason"]) for r in rows], [("5", "reopened")])

    def test_nothing_is_recorded_and_no_issue_is_listed_for_it_when_nothing_merged(self):
        self.tick(25)
        self.assertEqual(self.d.store.get_all("escaped"), {})
        self.assertFalse([c for c in self.w.gh_calls if c == ["issue", "list", "-R", "o/r", "--state", "open", "--json", "number", "--limit", "1000"]])
