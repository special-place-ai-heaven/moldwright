import contextlib, copy, io, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch as D
import pools
import roster
from test_dispatch import World, PR_LINE, ready

HERE = os.path.dirname(os.path.abspath(__file__))


def cw(i, runs=1):
    return {"id": i, "name": i.upper(), "runs": runs}


def mk(n, worker, folder="a/"):
    return {"number": n, "title": "T%d" % n, "comments": [],
            "body": ready().replace("**Worker**: coder", "**Worker**: " + worker).replace("a/", folder)}


class Specialists(unittest.TestCase):
    def world(self, types, issues, account=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = World(issues)
        cfg = {"repo": "o/r", "label": "factory", "checks_timeout_s": 3600, "auto_plan_marker": True, "types": types,
               "ledger_file": os.path.join(tmp.name, "ledger.db"), "json_state_file": os.path.join(tmp.name, "dispatch.json"),
               "heartbeat_file": os.path.join(tmp.name, "heartbeat")}
        self.w.ledger = cfg["ledger_file"]
        self.d = D.Dispatcher(cfg, account or self.w.account, self.w.gh, now=lambda: self.w.clock)
        self.addCleanup(self.d.close)
        return self.d

    def job(self, n):
        return self.d.store.get_job(str(n))

    def test_the_shipped_settings_give_each_narrower_type_the_roles_of_the_roster(self):
        types = D.settings()["types"]
        self.assertEqual(types["security"], {"max_jobs": 1, "role": "review", "coworkers": [
            {"id": "71dfdea8-3482-4f3f-b091-ed4b16a69b99", "name": "BRUCE", "runs": 3}]})
        self.assertEqual(types["data"], {"max_jobs": 1, "optional": True, "coworkers": [{"name": "CODD", "runs": 1}]})
        self.assertEqual(types["contracts"], {"max_jobs": 1, "role": "review", "optional": True,
                                              "coworkers": [{"name": "GRACE", "runs": 1}]})
        with open(os.path.join(HERE, "roster.json"), encoding="utf-8") as f:
            people = roster.load(f.read())["coworkers"]
        for t in ("coder", "data"):
            for c in types[t]["coworkers"]:
                self.assertEqual(people[c["name"].lower()]["github"], "writer", c["name"])
        for t, v in types.items():
            if v.get("role") == "review":
                for c in v["coworkers"]:
                    self.assertIn(people[c["name"].lower()]["github"], ("writer", "reviewer"), c["name"])
        runs = {}
        for v in types.values():
            for c in v["coworkers"]:
                runs.setdefault(c["name"], set()).add(c["runs"])
        self.assertEqual({n: r for n, r in runs.items() if len(r) > 1}, {})

    def test_the_pool_helpers_follow_the_role_of_the_type(self):
        cfg = {"types": {"coder": {}, "data": {}, "security": {"role": "review"}}}
        self.assertEqual([pools.build_pool(cfg, t) for t in ("coder", "data", "security", "x")], ["coder", "data", "coder", "x"])
        self.assertEqual([pools.review_pool(cfg, t) for t in ("coder", "data", "security", "x")], ["reviewer", "reviewer", "security", "reviewer"])

    def test_a_security_issue_is_built_by_a_coder_and_reviewed_first_by_its_type(self):
        d = self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1")]}, "reviewer": {"coworkers": [cw("r1")]},
                        "security": {"max_jobs": 1, "role": "review", "coworkers": [cw("s1")]}}, [mk(5, "security")])
        d.once()
        self.assertEqual(self.job(5)["pool"], "coder")
        self.w.finish("b1", PR_LINE)
        d.once()
        d.once()
        self.assertEqual([s[0] for s in self.w.sends], ["b1", "s1"])
        self.assertEqual(self.job(5)["state"], "reviewing")
        self.assertEqual(self.job(5)["pool"], "security")

    def test_a_data_issue_is_built_by_its_type_with_the_commands_spelled_out(self):
        d = self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1")]}, "reviewer": {"coworkers": [cw("r1")]},
                        "data": {"max_jobs": 1, "coworkers": [cw("d1")]}}, [mk(5, "data"), mk(6, "coder", "c/")])
        d.once()
        self.w.finish("d1", PR_LINE)
        d.once()
        d.once()
        self.assertEqual([s[0] for s in self.w.sends], ["d1", "b1", "r1"])
        sent = {a: m for a, m, _ in self.w.sends}
        for line in ("/data/tools/bin/wt new rerun 5 a1", "/data/tools/bin/packet rerun 5", "/data/tools/bin/pr-open --title"):
            self.assertIn(line, sent["d1"])
        self.assertNotIn("/data/tools/bin/wt new", sent["b1"])
        self.assertNotIn("/data/tools/bin/pr-open", sent["b1"])
        self.assertEqual(self.job(5)["pool"], "reviewer")

    def test_a_builder_is_never_sent_to_review_its_own_job(self):
        d = self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1", 2)]}, "reviewer": {"coworkers": [cw("b1", 2)]}}, [mk(5, "coder")])
        d.once()
        self.w.finish("b1", PR_LINE)
        d.once()
        d.once()
        self.assertEqual([s[0] for s in self.w.sends], ["b1"])
        self.assertEqual(self.job(5)["state"], "review_wait")
        self.assertEqual(self.job(5)["wait_reason"], "no free worker of its type")

    def test_an_optional_type_whose_coworker_is_not_found_is_left_out(self):
        cfg = copy.deepcopy(D.settings())
        full = [{"id": "s-1", "handle": "search", "name": "search"}, {"id": "d-1", "handle": "dieter", "name": "DIETER"}]

        def go(agents):
            w = World([mk(5, "data")])

            def account(tool, args):
                if tool == "list_agents":
                    return {"agents": agents}
                return w.account(tool, args)
            with tempfile.TemporaryDirectory() as t:
                c = copy.deepcopy(cfg)
                c.update(ledger_file=os.path.join(t, "ledger.db"), json_state_file=os.path.join(t, "dispatch.json"),
                         heartbeat_file=os.path.join(t, "heartbeat"))
                w.ledger = c["ledger_file"]
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    disp = D.Dispatcher(c, account, w.gh, now=lambda: w.clock)
                    try:
                        disp.once()
                    finally:
                        disp.close()
            return w, out.getvalue()
        w, out = go(full)
        self.assertIn("type data left out: coworker CODD is not in list_agents", out)
        self.assertIn("type contracts left out: coworker GRACE is not in list_agents", out)
        self.assertEqual(w.issue(5)["comments"], ["worker type data has no queue yet (phase B of #198)"])
        with self.assertRaises(D.Error) as e:
            go(full[:1])
        self.assertIn("DIETER", str(e.exception))

    def test_one_coworker_in_two_pools_takes_distinct_copies(self):
        d = self.world({"coder": {"max_jobs": 8, "coworkers": [cw("b1", 2)]}, "reviewer": {"coworkers": [{"id": "B", "name": "BRUCE", "runs": 3}]},
                        "security": {"max_jobs": 1, "role": "review", "coworkers": [{"id": "B", "name": "BRUCE", "runs": 3}]}},
                       [mk(5, "coder"), mk(6, "security", "c/")])
        d.once()
        self.assertEqual([s[0] for s in self.w.sends], ["b1", "b1"])
        self.w.runs["run1"] = {"status": "done", "output": PR_LINE, "error": None}
        self.w.runs["run2"] = {"status": "done", "output": PR_LINE.replace("/42", "/43"), "error": None}
        d.once()
        d.once()
        self.assertEqual([s[0] for s in self.w.sends], ["b1", "b1", "B", "B"])
        self.assertEqual({self.job(5)["copy"], self.job(6)["copy"]}, {1, 2})
        self.assertEqual((self.job(5)["pool"], self.job(6)["pool"]), ("reviewer", "security"))


if __name__ == "__main__":
    unittest.main()
