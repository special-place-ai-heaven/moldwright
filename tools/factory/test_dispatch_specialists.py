import contextlib, copy, io, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch as D
import pools
import roster
from test_dispatch import World, ready

HERE = os.path.dirname(os.path.abspath(__file__))
PR_42 = "Done.\nPR: https://github.com/o/r/pull/42"
PR_43 = "Done.\nPR: https://github.com/o/r/pull/43"


def cw(ids, runs=1):
    return [{"id": i, "name": i.upper(), "runs": runs} for i in ids]


def body(worker, folder="a"):
    return ready().replace("**Worker**: coder", "**Worker**: " + worker).replace("a/", folder + "/")


def job_issue(n, text):
    return {"number": n, "title": "T%d" % n, "comments": [], "body": text}


def done(agent, output):
    return lambda w: w.finish(agent, output)


def play(types, issues, steps, extra=None):
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(out):
        w = World(issues)
        cfg = {"repo": "o/r", "label": "factory", "checks_timeout_s": 3600, "auto_plan_marker": True, "types": types,
               "ledger_file": os.path.join(d, "ledger.db"), "json_state_file": os.path.join(d, "dispatch.json"),
               "heartbeat_file": os.path.join(d, "heartbeat")}
        cfg.update(extra or {})
        w.ledger = cfg["ledger_file"]
        disp = D.Dispatcher(cfg, w.account, w.gh, now=lambda: w.clock)
        try:
            for step in steps:
                if step == "once":
                    disp.once()
                else:
                    step(w)
            jobs = {j["issue"]: j for j in disp.jobs()}
        finally:
            disp.close()
    return w, jobs, out.getvalue()


class Specialists(unittest.TestCase):
    def test_the_shipped_settings_give_each_narrower_type_the_roles_of_the_roster(self):
        types = D.settings()["types"]
        self.assertEqual(types["security"], {"max_jobs": 1, "role": "review",
                                             "coworkers": [{"id": "71dfdea8-3482-4f3f-b091-ed4b16a69b99", "name": "BRUCE", "runs": 3}]})
        self.assertEqual(types["data"], {"max_jobs": 1, "optional": True, "coworkers": [{"name": "CODD", "runs": 1}]})
        self.assertEqual(types["contracts"], {"max_jobs": 1, "role": "review", "optional": True,
                                              "coworkers": [{"name": "GRACE", "runs": 1}]})
        with open(os.path.join(HERE, "roster.json"), encoding="utf-8") as f:
            people = roster.load(f.read())["coworkers"]
        for t in ("coder", "data"):
            for c in types[t]["coworkers"]:
                self.assertEqual(people[c["name"].lower()]["github"], "writer", c["name"])
        for t in ("security", "contracts"):
            for c in types[t]["coworkers"]:
                self.assertIn(people[c["name"].lower()]["github"], ("writer", "reviewer"), c["name"])
        runs = {}
        for t in types.values():
            for c in t["coworkers"]:
                runs.setdefault(c["name"], set()).add(c["runs"])
        self.assertTrue(all(len(v) == 1 for v in runs.values()), runs)
        builders = {c["name"] for t in ("coder", "data") for c in types[t]["coworkers"]}
        reviewers = {c["name"] for t in ("reviewer", "security", "contracts") for c in types[t]["coworkers"]}
        self.assertEqual(builders & reviewers, set())

    def test_the_pool_helpers_follow_the_role_of_the_type(self):
        cfg = D.settings()
        names = ("coder", "data", "security", "x")
        self.assertEqual([pools.build_pool(cfg, t) for t in names], ["coder", "data", "coder", "x"])
        self.assertEqual([pools.review_pool(cfg, t) for t in names], ["reviewer", "reviewer", "security", "reviewer"])

    def test_a_security_issue_is_built_by_a_coder_and_reviewed_first_by_its_type(self):
        types = {"coder": {"max_jobs": 8, "coworkers": cw(["b1"])}, "reviewer": {"coworkers": cw(["r1"])},
                 "security": {"max_jobs": 1, "role": "review", "coworkers": cw(["s1"])}}
        w, jobs, _ = play(types, [job_issue(5, body("security"))], ["once", done("b1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1", "s1"])
        self.assertEqual(jobs[5]["state"], "reviewing")
        self.assertEqual(jobs[5]["pool"], "security")

    def test_a_data_issue_is_built_by_its_type_with_the_commands_spelled_out(self):
        types = {"coder": {"max_jobs": 8, "coworkers": cw(["b1"])}, "reviewer": {"coworkers": cw(["r1"])},
                 "data": {"max_jobs": 1, "coworkers": cw(["d1"])}}
        w, jobs, _ = play(types, [job_issue(5, body("data")), job_issue(6, body("coder", "c"))],
                          ["once", done("d1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["d1", "b1", "r1"])
        sent = {s[0]: s[1] for s in w.sends}
        self.assertIn("/data/tools/bin/wt new rerun 5 a1", sent["d1"])
        self.assertIn("/data/tools/bin/packet rerun 5", sent["d1"])
        self.assertIn("/data/tools/bin/pr-open --title", sent["d1"])
        self.assertNotIn("/data/tools/bin/wt new", sent["b1"])
        self.assertNotIn("/data/tools/bin/pr-open", sent["b1"])
        self.assertEqual(jobs[5]["pool"], "reviewer")

    def test_a_builder_is_never_sent_to_review_its_own_job(self):
        types = {"coder": {"max_jobs": 8, "coworkers": cw(["b1"], 2)}, "reviewer": {"coworkers": cw(["b1"], 2)}}
        w, jobs, _ = play(types, [job_issue(5, body("coder"))], ["once", done("b1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1"])
        self.assertEqual(jobs[5]["state"], "review_wait")
        self.assertEqual(jobs[5]["wait_reason"], "no free worker of its type")

    def test_an_optional_type_whose_coworker_is_not_found_is_left_out(self):
        issue = job_issue(5, body("data"))
        found = [{"id": "s-1", "handle": "search", "name": "search"}, {"id": "d-1", "handle": "dieter", "name": "DIETER"}]
        with tempfile.TemporaryDirectory() as d:
            w = World([issue])
            cfg = copy.deepcopy(D.settings())
            cfg.update(ledger_file=os.path.join(d, "ledger.db"), json_state_file=os.path.join(d, "dispatch.json"),
                       heartbeat_file=os.path.join(d, "heartbeat"))
            w.ledger = cfg["ledger_file"]
            account = lambda tool, args: {"agents": found} if tool == "list_agents" else w.account(tool, args)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                disp = D.Dispatcher(cfg, account, w.gh, now=lambda: w.clock)
                try:
                    disp.once()
                finally:
                    disp.close()
            self.assertIn("type data left out: coworker CODD is not in list_agents", out.getvalue())
            self.assertIn("type contracts left out: coworker GRACE is not in list_agents", out.getvalue())
            self.assertEqual(w.issue(5)["comments"], ["worker type data has no queue yet (phase B of #198)"])
            lacking = [{"id": "s-1", "handle": "search", "name": "search"}, {"id": "c-1", "handle": "codd", "name": "CODD"},
                       {"id": "g-1", "handle": "grace", "name": "GRACE"}]
            again = copy.deepcopy(D.settings())
            again.update(ledger_file=cfg["ledger_file"], json_state_file=cfg["json_state_file"], heartbeat_file=cfg["heartbeat_file"])
            with self.assertRaises(D.Error) as e:
                D.Dispatcher(again, lambda tool, args: {"agents": lacking} if tool == "list_agents" else w.account(tool, args),
                             w.gh, now=lambda: w.clock)
            self.assertIn("DIETER", str(e.exception))

    def test_one_coworker_in_two_pools_takes_distinct_copies(self):
        types = {"coder": {"max_jobs": 8, "coworkers": cw(["b1"], 2)},
                 "reviewer": {"coworkers": [{"id": "B", "name": "B", "runs": 3}]},
                 "security": {"max_jobs": 1, "role": "review", "coworkers": [{"id": "B", "name": "B", "runs": 3}]}}

        def finish_both(w):
            for (r, _), out in zip([x for x in w.order if x[1] == "b1"], (PR_42, PR_43)):
                w.runs[r] = {"status": "done", "output": out, "error": None}
        w, jobs, _ = play(types, [job_issue(5, body("coder")), job_issue(6, body("security", "c"))],
                          ["once", finish_both, "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1", "b1", "B", "B"])
        copies = lambda agent: sorted(a["copyIndex"] for a in w.send_args if a["agentId"] == agent)
        self.assertEqual(copies("b1"), [1, 2])
        self.assertEqual(copies("B"), [1, 2])
        self.assertEqual({i: jobs[i]["pool"] for i in (5, 6)}, {5: "reviewer", 6: "security"})


if __name__ == "__main__":
    unittest.main()
