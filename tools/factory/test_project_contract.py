import json
import os
import unittest

import lines as L
from test_readiness import Hub
from test_lines import Pair

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "..", "..", "packages", "contracts", "fixtures", "factory-project.sample.json")
OTHER = "special-place-ai-heaven/testpilot"


def kinds(d):
    return {k: type(v).__name__ for k, v in d.items()}


class Contract(Pair):
    def setUp(self):
        super().setUp()
        with open(SAMPLE, encoding="utf-8") as f:
            self.sample = json.load(f)
        self.worlds[OTHER] = self.p
        self.p.ledger = L.ledger_path(self.cfg, OTHER)

    def new(self):
        d = super().new()
        d.gh = Hub(heads={"main"}, workflows=[])
        return d

    def test_the_dispatcher_takes_the_answer_of_the_sample_and_sends_the_fields_of_the_sample(self):
        self.tick()
        self.answer.update(self.sample["answer"])
        self.tick(2)
        self.assertEqual(self.d.active, OTHER)
        got, want = self.p.reports[-1], self.sample["snapshot"]
        self.assertEqual(set(want) - set(got), set())
        self.assertEqual(kinds(got["finishing"][0]), kinds(want["finishing"][0]))
        self.assertEqual(kinds(got["switch"]), kinds(want["switch"]))
        self.assertEqual(kinds(got["readiness"][0]), kinds(want["readiness"][0]))
        self.assertEqual([x["name"] for x in got["readiness"][0]["lines"]], [x["name"] for x in want["readiness"][0]["lines"]])
        self.assertEqual(kinds(got["readiness"][0]["lines"][0]), kinds(want["readiness"][0]["lines"][0]))
        self.assertEqual((got["readiness"][0]["base"], got["readiness"][0]["redgreen"]), (want["readiness"][0]["base"], want["readiness"][0]["redgreen"]))
        self.assertEqual(got["switch"]["by"], self.sample["answer"]["project"]["by"])

    def test_every_text_the_dispatcher_sends_fits_the_limits_of_the_contract(self):
        self.tick()
        self.answer.update(check=[OTHER], project={"repo": OTHER, "by": "x" * 500})
        self.tick(2)
        got = self.p.reports[-1]
        self.assertLessEqual(len(got["switch"]["by"]), 100)
        self.assertLessEqual(len(got["finishing"]), 10)
        self.assertLessEqual(len(got["readiness"]), 5)
        for r in got["readiness"]:
            self.assertLessEqual(len(r["lines"]), 12)
            self.assertTrue(all(len(x["text"]) <= 200 and 0 < len(x["name"]) <= 40 for x in r["lines"]))


if __name__ == "__main__":
    unittest.main()
