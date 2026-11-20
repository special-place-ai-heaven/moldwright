import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planning
from store import Store

ISSUE = {"number": 7, "title": "Something"}
DISPATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch.json")


class Rules(unittest.TestCase):
    def send_with(self, rules_cfg):
        tmp = tempfile.mkdtemp()
        st = Store(os.path.join(tmp, "s.db"))
        self.addCleanup(st.close)
        sent = []
        cfg = {"repo": "o/r", "planning": dict({"plan_by": ["One"], "cut_by": ["One"]}, **rules_cfg),
               "types": {"planner": {"coworkers": [{"id": "a1", "name": "One", "runs": 1}]}}}

        def account(tool, args):
            if tool == "send_message":
                sent.append(args)
                return {"runId": "r1", "status": "running"}
            return []

        station = planning.Station(cfg, st, account, lambda *a: "", lambda: 1000.0)
        self.assertTrue(station.send(ISSUE, ("a1", 1)))
        return sent[0]["message"], st.get_all("plan:7")

    def test_station_send_includes_rules_only_when_configured_and_records_version_in_kv(self):
        msg_on, rec_on = self.send_with({"rules": True})
        self.assertIn(planning.RULES, msg_on)
        self.assertEqual(rec_on.get("rules"), planning.RULES_V)

        msg_off, rec_off = self.send_with({"rules": False})
        self.assertNotIn(planning.RULES, msg_off)
        self.assertEqual(rec_off.get("rules"), "")

    def test_the_live_config_turns_them_on_for_the_planner(self):
        with open(DISPATCH, encoding="utf-8") as f:
            self.assertIs(json.load(f)["planning"].get("rules"), True)


if __name__ == "__main__":
    unittest.main()
