import contextlib, copy, io, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch as D
import pools
import roster
from test_dispatch import ACCEPT, HEAD, World, ready, wf

HERE = os.path.dirname(os.path.abspath(__file__))
PR_42 = "Done.\nPR: https://github.com/o/r/pull/42"
PR_43 = "Done.\nPR: https://github.com/o/r/pull/43"


def cw(*ids):
    return [{"id": i, "name": i.upper()} for i in ids]


def body(worker, folder="a"):
    return ready().replace("**Worker**: coder", "**Worker**: " + worker).replace("a/", folder + "/")


def job_issue(n, text):
    return {"number": n, "title": "T%d" % n, "comments": [], "body": text}


def done(agent, output):
    return lambda w: w.finish(agent, output)


class RuntimeWorld(World):
    def __init__(self, issues, seats):
        super().__init__(issues)
        self.seats = seats
        self.foreign_ghosts, self.beats, self.head = [], [], HEAD

    def gh(self, args):
        out = super().gh(args)
        return json.dumps(dict(json.loads(out), headRefOid=self.head)) if args[:2] == ["pr", "view"] else out


def play(types, issues, steps, seats=None, limit=8, **extra):
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(out):
        cfg = {"repo": "o/r", "label": "factory", "checks_timeout_s": 3600, "auto_plan_marker": True, "types": types,
               "ledger_file": os.path.join(d, "ledger.db"), "json_state_file": os.path.join(d, "dispatch.json"),
               "heartbeat_file": os.path.join(d, "heartbeat")}
        members = {}
        for t in types.values():
            for c in t["coworkers"]:
                members.setdefault(c["name"], set()).add(c["id"])
        w = RuntimeWorld(issues, dict.fromkeys(members, 1) | (seats or {}))
        cfg.update(extra, pool={"max": limit, "seats": w.seats, "members": members, "ghosts": lambda: disp.ghosts() + w.foreign_ghosts})
        w.ledger = cfg["ledger_file"]
        disp = D.Dispatcher(cfg, w.account, w.gh, now=lambda: w.clock)
        try:
            for step in steps:
                if step == "once":
                    disp.once()
                    w.beats.append({j["issue"]: j for j in disp.jobs()})
                else:
                    step(w)
            jobs = {j["issue"]: j for j in disp.jobs()}
        finally:
            disp.close()
    return w, jobs, out.getvalue()


class Specialists(unittest.TestCase):
    def test_the_shipped_settings_give_each_narrower_type_the_roles_of_the_roster(self):
        types = D.settings()["types"]
        bruce = {"id": "71dfdea8-3482-4f3f-b091-ed4b16a69b99", "name": "BRUCE", "provider": "openrouter"}
        self.assertEqual(types["security"], {"role": "review", "coworkers": [bruce]})
        self.assertIn(bruce, types["reviewer"]["coworkers"])
        self.assertEqual(types["data"], {"optional": True, "coworkers": [{"name": "CODD"}]})
        self.assertEqual(types["contracts"], {"role": "review", "optional": True, "coworkers": [{"name": "GRACE"}]})
        with open(os.path.join(HERE, "roster.json"), encoding="utf-8") as f:
            people = roster.load(f.read())["coworkers"]
        for t in ("coder", "data"):
            for c in types[t]["coworkers"]:
                self.assertEqual(people[c["name"].lower()]["github"], "writer", c["name"])
        for t in ("security", "contracts"):
            for c in types[t]["coworkers"]:
                self.assertIn(people[c["name"].lower()]["github"], ("writer", "reviewer"), c["name"])

        builders = {c["name"] for t in ("coder", "data") for c in types[t]["coworkers"]}
        reviewers = {c["name"] for t in ("reviewer", "security", "contracts") for c in types[t]["coworkers"]}
        self.assertEqual(builders & reviewers, set())

    def test_the_pool_helpers_follow_the_role_of_the_type(self):
        cfg = D.settings()
        names = ("coder", "data", "security", "x")
        self.assertEqual([pools.build_pool(cfg, t) for t in names], ["coder", "data", "coder", "x"])
        self.assertEqual([pools.review_pool(cfg, t) for t in names], ["reviewer", "reviewer", "security", "reviewer"])

    def test_a_security_issue_is_built_by_a_coder_and_reviewed_first_by_its_type(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "security": {"role": "review", "coworkers": cw("s1")}}
        w, jobs, _ = play(types, [job_issue(5, body("security"))], ["once", done("b1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1", "s1"])
        self.assertEqual(w.beats[0][5]["pool"], "coder")
        self.assertEqual(jobs[5]["state"], "reviewing")
        self.assertEqual(jobs[5]["pool"], "security")

    def test_a_data_issue_is_built_by_its_type_with_the_commands_spelled_out(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "data": {"coworkers": cw("d1")}}
        w, jobs, _ = play(types, [job_issue(5, body("data")), job_issue(6, body("coder", "c"))],
                          ["once", done("d1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["d1", "b1", "r1"])
        sent = {s[0]: s[1] for s in w.sends}
        self.assertIn("/data/tools/bin/wt new rerun 5 a1", sent["d1"])
        self.assertIn("/data/tools/bin/packet rerun 5", sent["d1"])
        self.assertIn("/data/tools/bin/pr-open --title", sent["d1"])
        self.assertLess(sent["d1"].index("`## Asks`"), sent["d1"].index("Open it with `cd <worktree>"))
        self.assertNotIn("/data/tools/bin/wt new", sent["b1"])
        self.assertNotIn("/data/tools/bin/pr-open", sent["b1"])
        self.assertEqual(jobs[5]["pool"], "reviewer")
        self.assertEqual(w.beats[0][5]["pool"], "data")

    def test_a_builder_is_never_sent_to_review_its_own_job(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("b1")}}
        w, jobs, _ = play(types, [job_issue(5, body("coder"))], ["once", done("b1", PR_42), "once", "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1"])
        self.assertEqual(jobs[5]["state"], "review_wait")
        self.assertEqual(jobs[5]["wait_reason"], "no free worker of its type")

    def test_an_optional_type_whose_coworker_is_not_found_is_left_out(self):
        issues = [job_issue(5, body("data")), job_issue(6, body("contracts", "c"))]
        found = [{"id": "s-1", "handle": "search", "name": "search"}, {"id": "d-1", "handle": "dieter", "name": "DIETER"}]
        with tempfile.TemporaryDirectory() as d:
            w = World(issues)
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
            self.assertEqual(w.issue(6)["comments"], ["worker type contracts has no queue yet (phase B of #198)"])
            self.assertEqual(w.sends, [])
            lacking = [{"id": "s-1", "handle": "search", "name": "search"}, {"id": "c-1", "handle": "codd", "name": "CODD"},
                       {"id": "g-1", "handle": "grace", "name": "GRACE"}]
            again = copy.deepcopy(D.settings())
            again.update(ledger_file=cfg["ledger_file"], json_state_file=cfg["json_state_file"], heartbeat_file=cfg["heartbeat_file"])
            with self.assertRaises(D.Error) as e:
                D.Dispatcher(again, lambda tool, args: {"agents": lacking} if tool == "list_agents" else w.account(tool, args),
                             w.gh, now=lambda: w.clock)
            self.assertIn("DIETER", str(e.exception))

    def test_one_coworker_in_two_pools_takes_distinct_copies(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("B")},
                 "security": {"role": "review", "coworkers": cw("B")}}

        def finish_both(w):
            for (r, _), out in zip([x for x in w.order if x[1] == "b1"], (PR_42, PR_43)):
                w.runs[r] = {"status": "done", "output": out, "error": None}
        w, jobs, _ = play(types, [job_issue(5, body("coder")), job_issue(6, body("security", "c"))],
                          ["once", finish_both, "once", "once"], seats={"B1": 2, "B": 2})
        self.assertEqual([s[0] for s in w.sends], ["b1", "b1", "B", "B"])
        copies = lambda agent: sorted(a["copyIndex"] for a in w.send_args if a["agentId"] == agent)
        self.assertEqual(copies("b1"), [1, 2])
        self.assertEqual(copies("B"), [1, 2])
        self.assertEqual({i: jobs[i]["pool"] for i in (5, 6)}, {5: "reviewer", 6: "security"})

    def test_admission_needs_both_specialist_and_coder_seats_and_builds_share_coder_capacity(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "contracts": {"role": "review", "coworkers": cw("s1")}}
        issues = [job_issue(5, body("coder")), job_issue(6, body("contracts", "c")), job_issue(7, body("contracts", "d")),
                  job_issue(8, body("reviewer", "e"))]
        for seats in ({"B1": 0}, {"S1": 0}):
            with self.subTest(seats=seats):
                w, jobs, _ = play(types, issues, ["once"], seats=seats)
                self.assertNotIn(6, jobs)
                self.assertNotIn(8, jobs)
        issues[3]["comments"].clear()
        w, jobs, _ = play(types, issues, ["once", done("b1", PR_42), "once"])
        self.assertEqual(w.beats[0][6]["state"], "queued")
        self.assertEqual((jobs[6]["agent"], jobs[6]["pool"]), ("b1", "coder"))
        self.assertNotIn(7, jobs)
        self.assertNotIn(8, jobs)
        self.assertEqual(w.issue(8)["comments"], ["worker type reviewer has no queue yet (phase B of #198)"])

    def test_gate_second_review_and_acceptor_proof_exclude_the_build_and_both_reviewers(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("b1", "s1", "r1")},
                 "security": {"role": "review", "coworkers": cw("b1", "s1")}, "acceptor": {"coworkers": cw("a1")}}
        gate = body("security").replace("a/b.py", "tools/factory/dispatch.py")
        w, jobs, _ = play(types, [job_issue(5, gate)],
                          [lambda w: w.workflows.update({HEAD: [wf("ci", "success")]}), "once", done("b1", PR_42), "once", "once",
                           done("s1", ACCEPT), "once", "once", done("r1", ACCEPT), "once", "once", "once"], proof=True)
        self.assertEqual([s[0] for s in w.sends], ["b1", "s1", "r1", "a1"])
        self.assertEqual(w.beats[4][5]["pool"], "reviewer")
        self.assertEqual((jobs[5]["state"], jobs[5]["pool"]), ("proving", "acceptor"))

    def test_a_changed_head_starts_a_new_first_review_in_the_specialist_pool(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "security": {"role": "review", "coworkers": cw("s1")}}
        gate = body("security").replace("a/b.py", "tools/factory/dispatch.py")
        w, jobs, _ = play(types, [job_issue(5, gate)],
                          ["once", done("b1", PR_42), "once", "once", done("s1", ACCEPT), "once",
                           lambda w: setattr(w, "head", "1234567123456789"), "once"])
        self.assertEqual([s[0] for s in w.sends], ["b1", "s1", "s1"])
        self.assertEqual((jobs[5]["pool"], jobs[5]["first_accept"]), ("security", None))

    def test_a_proven_contract_fix_waits_for_a_coder_seat_and_records_its_pool(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "contracts": {"role": "review", "coworkers": cw("s1")}}

        def proven(w):
            w.branches["plan/5"] = "sha5aaaaaaaaaaa"
            w.compare_files = ["a/b.py"]

        w, jobs, _ = play(types, [job_issue(5, "**Proven branch**: plan/5\n" + body("contracts"))],
                          [proven, "once", "once", done("s1", "VERDICT: REJECT @abcdef1: wrong"), "once",
                           lambda w: w.foreign_ghosts.append(("b1", 1)), "once", lambda w: w.foreign_ghosts.clear(), "once"])
        self.assertEqual([s[0] for s in w.sends], ["s1", "b1"])
        self.assertEqual(w.beats[3][5]["state"], "fix_wait")
        self.assertEqual((jobs[5]["state"], jobs[5]["pool"], jobs[5]["builder"]), ("fixing", "coder", "b1"))

    def test_a_regular_specialist_fix_returns_to_the_original_builder_and_pool(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "data": {"coworkers": cw("d1", "d2")}}
        w, jobs, _ = play(types, [job_issue(5, body("data"))],
                          ["once", done("d1", PR_42), "once", "once", done("r1", "VERDICT: REJECT @abcdef1: wrong"), "once",
                           lambda w: w.foreign_ghosts.append(("d1", 1)), "once", lambda w: w.foreign_ghosts.clear(), "once"])
        self.assertEqual([s[0] for s in w.sends], ["d1", "r1", "d1"])
        self.assertEqual(w.beats[4][5]["state"], "fix_wait")
        self.assertEqual((jobs[5]["state"], jobs[5]["pool"]), ("fixing", "data"))

    def test_specialist_retry_keeps_its_pool_but_never_resends_without_a_runtime_seat(self):
        types = {"coder": {"coworkers": cw("b1")}, "reviewer": {"coworkers": cw("r1")},
                 "security": {"role": "review", "coworkers": cw("s1")}}
        issue = job_issue(5, body("security"))

        def fail(w):
            w.finish("s1", "", status="error")

        for reduce_seats in (False, True):
            with self.subTest(reduce_seats=reduce_seats):
                w, jobs, _ = play(types, [issue], ["once", done("b1", PR_42), "once", "once", fail,
                                  lambda w: w.seats.update(S1=int(not reduce_seats)), "once", "once",
                                  lambda w: w.seats.update(S1=1), "once", fail, "once"], limit=1)
                self.assertEqual(w.beats[3][5]["state"], "review_wait" if reduce_seats else "reviewing")
                self.assertEqual(w.beats[4][5]["state"], "review_wait" if reduce_seats else "reviewing")
                self.assertEqual([s[0] for s in w.sends], ["b1", "s1", "s1"])
                self.assertEqual((jobs[5]["state"], jobs[5]["pool"], jobs[5]["attempt"]), ("failed", "security", 2))


if __name__ == "__main__":
    unittest.main()
