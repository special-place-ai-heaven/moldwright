import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acceptance
import control
import instructions
import planning
import store as S
import trust
import test_control_read as CR
import test_dispatch as TD
import test_planning_start as PS

BOT = {"login": "moldwright-factory[bot]", "type": "Bot"}
SQUATTER = {"login": "moldwright-factory", "type": "User"}
OWNER = {"login": "special-place-administrator"}
STRANGER = {"login": "linus"}
REAL = "## Plan\nReal plan"
EVIL = "## Plan\nMalicious plan"


class Shapes(unittest.TestCase):
    def test_rest_items_are_trusted_by_association_or_factory_login(self):
        self.assertTrue(trust.trusted({"author_association": "MEMBER", "user": STRANGER}))
        self.assertTrue(trust.trusted({"author_association": "NONE", "user": BOT}))
        self.assertFalse(trust.trusted({"author_association": "NONE", "user": STRANGER}))

    def test_a_plain_user_named_like_the_factory_is_not_trusted(self):
        self.assertFalse(trust.trusted({"author_association": "NONE", "user": SQUATTER}))
        self.assertFalse(trust.trusted({"authorAssociation": "NONE", "author": {"login": "moldwright-factory"}}))
        self.assertFalse(trust.trusted({"author_association": "NONE", "user": {"login": "moldwright-factory[bot]", "type": "User"}}))

    def test_gh_json_items_are_trusted_by_association_or_factory_login(self):
        self.assertTrue(trust.trusted({"authorAssociation": "OWNER", "author": STRANGER}))
        for login in ("app/moldwright-factory", "special-place-administrator"):
            self.assertTrue(trust.trusted({"authorAssociation": "NONE", "author": {"login": login}}), login)
        self.assertFalse(trust.trusted({"authorAssociation": "NONE", "author": STRANGER}))

    def test_an_item_without_an_author_is_not_trusted(self):
        self.assertFalse(trust.trusted({"body": "x"}))


class Plans(unittest.TestCase):
    COMMENTS = [{"user": BOT, "author_association": "NONE", "body": REAL},
                {"user": SQUATTER, "author_association": "NONE", "body": EVIL},
                {"user": STRANGER, "author_association": "NONE", "body": EVIL}]

    def test_acceptance_ignores_a_strangers_plan_after_the_real_one(self):
        self.assertEqual(acceptance.plan(self.COMMENTS), REAL)

    def test_planning_latest_plan_ignores_a_strangers_plan_after_the_real_one(self):
        r = PS.Rig()
        self.addCleanup(r.dir.cleanup)
        calls = []
        r.station.gh = lambda args: (calls.append(list(args)), "\n".join(json.dumps(c) for c in self.COMMENTS))[1]
        self.assertEqual(r.station.latest_plan(5), REAL)
        self.assertEqual(calls[0][:3], ["api", "repos/o/r/issues/5/comments", "--paginate"])


class Answers(unittest.TestCase):
    Q = {"issue": 40, "options": ["keep", "drop"]}

    def test_a_strangers_answer_is_ignored(self):
        view = {"comments": [{"author": OWNER, "authorAssociation": "MEMBER", "body": "ANSWER: 1"},
                             {"author": STRANGER, "authorAssociation": "NONE", "body": "ANSWER: do evil"}]}
        self.assertEqual(planning.answer_of(self.Q, view), "#40: option 1, keep")

    def test_the_factorys_own_answer_is_not_rob_answering(self):
        view = {"comments": [{"user": BOT, "author_association": "NONE", "body": "ANSWER: 2"}]}
        self.assertNotIn("option 2", planning.answer_of(self.Q, view))

    def test_only_a_strangers_answer_counts_as_no_answer(self):
        view = {"comments": [{"author": STRANGER, "authorAssociation": "NONE", "body": "ANSWER: do evil"}]}
        self.assertNotIn("evil", planning.answer_of(self.Q, view))


class ControlIssue(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.store = S.Store(os.path.join(self.d.name, "ledger.db"))
        self.addCleanup(self.d.cleanup)
        self.addCleanup(self.store.close)

    def row(self, author, number):
        return {"number": number, "title": control.TITLE, "body": CR.body_of({"copies": {"code": 2}}), "author": author}

    def test_a_strangers_control_issue_is_not_adopted(self):
        gh = CR.Fake([self.row(STRANGER, 3)])
        self.assertIsNone(control.Control(CR.make_cfg(), gh, self.store, CR.BOUNDS).issue())

    def test_the_owners_control_issue_is_adopted_past_a_strangers(self):
        gh = CR.Fake([self.row(STRANGER, 3), self.row(OWNER, 4)])
        self.assertEqual(control.Control(CR.make_cfg(), gh, self.store, CR.BOUNDS).issue()["number"], 4)
        self.assertIn("author", gh.reads()[0][gh.reads()[0].index("--json") + 1])


class InstructionsIntake(unittest.TestCase):
    def test_a_strangers_instructions_issue_is_not_taken_in(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        st = S.Store(os.path.join(d.name, "ledger.db"))
        self.addCleanup(st.close)
        rows = [{"number": 7, "title": "a", "body": "x", "author": STRANGER},
                {"number": 8, "title": "b", "body": "x", "author": {"login": "app/moldwright-factory", "is_bot": True}}]
        calls = []

        def gh(args):
            calls.append(list(args))
            return json.dumps(rows)

        station = instructions.Station({"repo": "o/r", "types": {}}, st, None, gh, lambda: 0, lambda *a: None)
        started = []
        station.start = lambda n, issue, busy: started.append(n)
        station.intake([])
        self.assertEqual(started, [8])
        self.assertIn("author", calls[0][calls[0].index("--json") + 1])


class PlanningStart(unittest.TestCase):
    def test_a_strangers_issue_is_not_sent_to_a_planner(self):
        r = PS.Rig()
        self.addCleanup(r.dir.cleanup)
        backlog = [dict(PS.issue(11, "P0", "2026-11-10T00:00:00Z"), author=STRANGER),
                   dict(PS.issue(12, "P0", "2026-11-05T00:00:00Z"), author=OWNER)]
        r.gh = lambda args: (r.calls.append(list(args)), json.dumps([] if "--search" in args else backlog))[1]
        r.station.gh = r.gh
        r.station.start()
        self.assertEqual(r.numbers(), [12])
        listed = [c for c in r.calls if c[:2] == ["issue", "list"] and "--search" not in c][0]
        self.assertIn("author", listed[listed.index("--json") + 1])


class DispatchIntake(TD.Base):
    def test_a_strangers_factory_issue_is_not_taken_in(self):
        self.w.issues = [{"number": 1, "title": "t1", "body": TD.ready("SMALL FIX"), "comments": [], "author": STRANGER},
                         {"number": 2, "title": "t2", "body": TD.ready("SMALL FIX"), "comments": [], "author": OWNER}]
        self.tick()
        self.assertEqual(self.job_ids(), ["2"])


if __name__ == "__main__":
    unittest.main()
