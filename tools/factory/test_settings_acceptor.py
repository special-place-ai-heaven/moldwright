import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control
import pools

HERE = os.path.dirname(os.path.abspath(__file__))
BARBARA = {"id": "b0e5b39f-74e3-4dfd-9d16-8cf53934ad05", "name": "BARBARA", "runs": 2}


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


class SettingsAcceptor(unittest.TestCase):
    def test_the_shipped_settings_have_the_acceptor_type_with_barbara_at_two_runs(self):
        cfg = load("dispatch.json")
        acceptor = cfg["types"]["acceptor"]
        self.assertEqual(acceptor["coworkers"], [BARBARA])
        self.assertNotIn("max_jobs", acceptor)
        pool = pools.types({"types": {"acceptor": acceptor}})["acceptor"]
        self.assertEqual(pool["coworkers"], [BARBARA])
        self.assertEqual(pool["coworkers"][0]["runs"], 2)
        self.assertIsNone(pool["max_jobs"])

    def test_barbara_has_a_bound_of_three_copies(self):
        self.assertEqual(load("control-bounds.json")["copies"]["BARBARA"], 3)

    def test_the_control_block_may_set_her_copies_up_to_the_bound(self):
        bounds = load("control-bounds.json")
        base = {"copies": {"BARBARA": 2}}
        effective, errors = control.validate({"copies": {"BARBARA": 3}}, bounds, base, None)
        self.assertEqual(effective["copies"]["BARBARA"], 3)
        self.assertEqual(errors, [])
        effective, errors = control.validate({"copies": {"BARBARA": 4}}, bounds, base, None)
        self.assertEqual(effective["copies"]["BARBARA"], 2)
        self.assertEqual(len(errors), 1)

    def test_every_coworker_of_the_settings_has_a_bound(self):
        names = {c["name"] for t in load("dispatch.json")["types"].values() for c in t["coworkers"]}
        self.assertEqual(names - set(load("control-bounds.json")["copies"]), set())


if __name__ == "__main__":
    unittest.main()
