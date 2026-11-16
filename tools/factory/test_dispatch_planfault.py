import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof
import dispatch as D
from test_dispatch_proof import ProofBase, met

HEAD = "abcdef1234567890"
PLAN2 = "ASK 2: NOT MET (plan) Files lacks tools/x.py"
PLAN5 = "ASK 5: NOT MET (plan) the Run line is not in the Run block"


def lines(*extra):
    return "\n".join(extra)


class Judge(unittest.TestCase):
    def test_every_not_met_of_kind_plan_is_a_plan_result(self):
        for tail in ("PROOF: PASS @abcdef1", "PROOF: FAIL @abcdef1: 2, 5"):
            out = "ASK 1: MET a:1 t\n%s\n%s\n%s" % (PLAN2, PLAN5, tail)
            self.assertEqual(proof.judge(out, 5, HEAD), ("plan", PLAN2 + "\n" + PLAN5))
        long = "ASK 2: NOT MET (plan) " + "x" * 3000 + "\nPROOF: FAIL @abcdef1: 2"
        kind, text = proof.judge(long, 5, HEAD)
        self.assertEqual((kind, len(text)), ("plan", 1500))

    def test_one_plain_not_met_keeps_it_a_fail(self):
        body = met(notmet=(3,)).replace("ASK 2: MET a/b.py:2 test_2", PLAN2)
        for tail in ("PROOF: FAIL @abcdef1: 2, 3", "PROOF: PASS @abcdef1"):
            self.assertEqual(proof.judge(body + "\n" + tail, 5, HEAD)[0], "fail")

    def test_a_plan_line_under_another_commit_is_none(self):
        out = "%s\nPROOF: FAIL @1234567: 2" % PLAN2
        self.assertEqual(proof.judge(out, 5, HEAD)[0], "none")


class Fault(ProofBase):
    def setUp(self):
        super().setUp()
        self.cfg["types"] = {
            "coder": {"max_jobs": 8, "coworkers": [{"id": "b1", "name": "B1", "runs": 1}]},
            "reviewer": {"coworkers": [{"id": "r1", "name": "R1", "runs": 1}, {"id": "r2", "name": "R2", "runs": 1}]},
            "planner": {"coworkers": [{"id": "p1", "name": "Boss", "runs": 1}, {"id": "p2", "name": "IKE", "runs": 1}]},
        }

    def data(self):
        return json.loads(self.w.rows("SELECT data FROM jobs WHERE job='5'")[0][0])

    def planner_sends(self):
        return [s for s in self.w.sends if s[0] in ("p1", "p2")]

    def builder_sends(self):
        return [s for s in self.w.sends if s[0] == "b1"]

    def plan_proof(self):
        return met(notmet=(2,)).replace("ASK 2: NOT MET no test", PLAN2) + "\nPROOF: FAIL @abcdef1: 2"

    def test_a_plan_proof_returns_the_job_and_the_re_plan_carries_the_provers_lines(self):
        self.to_proving()
        builds = len(self.builder_sends())
        self.w.finish("r2", self.plan_proof())
        self.tick(2)
        self.assertEqual(self.state(), "returned")
        self.assertTrue(self.data()["reason"].startswith("plan: proof:"))
        self.assertEqual(len(self.builder_sends()), builds)
        sent = self.planner_sends()
        self.assertEqual(len(sent), 1)
        self.assertIn(PLAN2, sent[0][1])
        self.assertIn("#", sent[0][1])
        self.assertIn("Pull request #%s" % self.data()["pr"], sent[0][1])
        self.assertEqual(self.data()["replans"], 1)

    def test_a_plan_proof_in_round_two_is_returned_not_rejected(self):
        self.to_proving()
        self.w.finish("r2", "PROOF: FAIL @abcdef1: 4, 5")
        self.tick(2)
        self.w.finish("b1", "PUSHED: fix")
        self.tick(2)
        self.w.finish("r1", "ok\nVERDICT: ACCEPT @abcdef1")
        self.tick(3)
        self.assertEqual(self.state(), "proving")
        self.w.finish("r2", self.plan_proof())
        self.tick()
        self.assertEqual(self.state(), "returned")
        self.assertTrue(self.data()["reason"].startswith("plan: proof:"))

    def test_a_review_reject_plan_goes_to_the_re_plan(self):
        self.to_review()
        builds = len(self.builder_sends())
        verdict = "VERDICT: REJECT (plan) @abcdef1: Files lacks a path"
        self.w.finish("r1", "no\n" + verdict)
        self.tick(2)
        self.assertEqual(self.state(), "returned")
        self.assertTrue(self.data()["reason"].startswith("plan: review: "))
        self.assertEqual(len(self.builder_sends()), builds)
        sent = self.planner_sends()
        self.assertEqual(len(sent), 1)
        self.assertIn(verdict, sent[0][1])

    def test_a_plain_reject_still_goes_to_the_fix(self):
        self.to_review()
        self.w.finish("r1", "no\nVERDICT: REJECT @abcdef1: wrong")
        self.tick()
        self.assertEqual(self.state(), "fix_wait")
        self.assertEqual(self.planner_sends(), [])

    def test_the_proof_brief_names_the_plan_form(self):
        self.to_proving()
        self.assertIn("NOT MET (plan)", self.w.sends[-1][1])

    def test_the_review_brief_names_the_plan_form(self):
        self.to_review()
        self.assertIn("VERDICT: REJECT (plan) @", self.w.sends[-1][1])

    def test_the_re_plan_brief_says_the_pull_request_is_open(self):
        self.to_proving()
        self.w.finish("r2", self.plan_proof())
        self.tick(2)
        brief = self.planner_sends()[0][1]
        self.assertIn("Pull request #%s is open" % self.data()["pr"], brief)
        self.assertIn(PLAN2, brief)


if __name__ == "__main__":
    unittest.main()
