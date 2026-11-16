import json
import unittest

import lines as L
import test_dispatch_proof as P
from test_dispatch import Base
from test_lines import Pair


class OtherBase(Base):
    def compare(self, **cfg):
        self.cfg.update(cfg)
        self.d = self.new()
        self.d.stale_files({"issue": 5, "plan_dev": "4296d1f", "paths": ["a/b.py"]})
        return [a[1] for a in self.w.gh_calls if a[0] == "api" and "/compare/" in a[1]]

    def test_the_plan_is_compared_with_the_base_branch_of_the_project(self):
        self.assertEqual(self.compare(repo="p/q", home="o/r", base="main"), ["repos/p/q/compare/4296d1f...main"])

    def test_at_home_and_without_a_base_it_is_dev_as_before(self):
        self.assertEqual(self.compare(), ["repos/o/r/compare/4296d1f...dev"])


class StandIn(P.ProofBase):
    def test_without_the_red_green_check_the_prover_gets_it_as_the_last_ask(self):
        self.cfg.update(repo="p/q", home="o/r", redgreen=False)
        self.to_proving()
        msg = self.w.sends[-1][1]
        asks = [x for x in msg.split("\n") if x.startswith("ASK ")]
        self.assertEqual(len(asks), 6)
        self.assertIn('ASK 6: This project has no check "Done-test red before green", so you run it', msg)
        self.assertIn("/data/tools/bin/wt new p/q 5 p1", asks[-1])
        self.w.finish(self.w.sends[-1][0], P.MET + "\nPROOF: PASS @" + P.HEAD[:7])
        self.tick()
        self.assertEqual(self.state(), "proof_wait")
        self.assertEqual(self.w.merges, [])

    def test_with_the_check_the_asks_are_the_issue_s_own(self):
        self.to_proving()
        self.assertEqual(len([x for x in self.w.sends[-1][1].split("\n") if x.startswith("ASK ")]), 5)
        self.assertNotIn("so you run it", self.w.sends[-1][1])


class Facts(Pair):
    def test_a_line_takes_base_and_proof_from_the_readiness_recorded_here(self):
        self.d = self.new()
        self.d.kv.set("-", "ready:p/q", json.dumps({"passed": True, "base": "main", "redgreen": False}))
        self.select("p/q")
        self.tick(2)
        line = self.d.lines["p/q"]
        self.assertEqual((line.base, line.cfg["redgreen"]), ("main", False))
        home = self.d.lines["o/r"]
        self.assertEqual((home.base, home.cfg.get("redgreen", True)), ("dev", True))

    def test_a_record_without_them_means_dev_and_the_stand_in(self):
        cfg = L.line_cfg(self.cfg, "p/q", {"passed": True})
        self.assertEqual((cfg["base"], cfg["redgreen"]), ("dev", False))
        self.assertIs(L.line_cfg(self.cfg, "o/r"), self.cfg)


if __name__ == "__main__":
    unittest.main()
