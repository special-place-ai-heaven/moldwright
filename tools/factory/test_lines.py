import contextlib
import io
import json
import os
import shutil
import sqlite3
import unittest
import unittest.mock

import dispatch as D
import lines as L
import pools
import resolver as R
import store as S
from test_dispatch import HEAD, PR_LINE, Base, World, ready, wf


def issue(n, title="Other", deps="none"):
    return {"number": n, "title": title, "body": ready(deps=deps), "comments": []}


class Pair(Base):
    def setUp(self):
        super().setUp()
        self.p = World([issue(5)])
        self.p.ledger = L.ledger_path(self.cfg, "p/q")
        self.worlds = {"o/r": self.w, "p/q": self.p}
        self.answer = {"kept": True}
        self.w.report_answer = self.p.report_answer = self.answer

    def new(self):
        clock = lambda: self.w.clock
        with contextlib.redirect_stdout(self.out):
            return L.Lines(self.cfg, None, None, now=clock, make=lambda c: D.Dispatcher(
                c, self.worlds[c["repo"]].account, self.worlds[c["repo"]].gh, now=clock))

    def seed(self, control=True, repo="o/r"):
        s = S.Store(self.cfg["ledger_file"])
        at = "2026-11-23T00:00:00Z"
        if control:
            s.set("-", "control", json.dumps({"state": "RUNNING", "by": "test", "at": at}))
        s.set("-", "project", json.dumps({"repo": repo, "from": None, "by": "test", "at": at}))
        s.add_event("project", None, s.get_all("-")["project"])
        s.set("-", "work_order", json.dumps({"id": "seed", "repo": repo, "kind": "all_issues", "issues": [5, 6, 7, 8], "text": "", "by": "test", "at": at}))
        s.set("-", "throttle", json.dumps({"max_ghosts": 1, "stations": {}, "by": "test", "at": at}))
        s.close()

    def start(self, passed=True):
        self.seed()
        self.d = self.new()
        if passed:
            self.d.kv.set("-", "ready:p/q", json.dumps({"passed": True}))

    def select(self, repo, by="rob", order=True):
        self.answer["project"] = {"repo": repo, "by": by}
        if order:
            self.answer["work_order"] = {"id": "seed-" + repo.replace("/", "-"), "repo": repo, "kind": "all_issues", "issues": [5, 6, 7, 8], "by": by, "at": "2026-11-23T00:00:00Z"}

    def widen(self):
        self.answer["throttle"] = {"max_ghosts": 2, "stations": {}, "by": "rob", "at": D.iso(self.w.clock)}

    def lines_said(self, text):
        return [x for x in self.out.getvalue().split("\n") if text in x]


class Two(Pair):
    def test_the_default_project_is_the_home_and_an_app_without_an_answer_changes_nothing(self):
        self.start()
        self.tick(3)
        self.assertEqual(self.d.active, "o/r")
        self.assertEqual(self.state(), "building")
        self.assertEqual(self.p.sends, [])
        self.assertEqual(self.w.reports[-1]["home"], "o/r")
        self.assertEqual(self.w.reports[-1]["finishing"], [])

    def test_the_ledger_of_today_is_carried_over_as_the_home_ledger(self):
        d = D.Dispatcher(self.cfg, self.w.account, self.w.gh, now=lambda: self.w.clock)
        with contextlib.redirect_stdout(self.out):
            d.once()
        d.store.set("plan:12", "state", "planning")
        d.store.set("-", "hold:sign-in renewal", json.dumps({"until": 5}))
        d.store.add_failure("problem", "5", station="resolve", reason="x")
        d.close()
        db = sqlite3.connect(self.cfg["ledger_file"])
        db.execute("DELETE FROM kv WHERE k='project_of'")
        db.commit()
        dump = lambda: {t: db.execute("SELECT * FROM %s ORDER BY 1, 2" % t).fetchall() for t in ("jobs", "fires", "transitions", "failures", "kv")}
        before = dump()
        self.assertEqual([r[0] for r in before["jobs"]], ["5"])
        self.start(passed=False)
        after = dump()
        self.assertEqual(self.w.rows("SELECT v FROM kv WHERE job='-' AND k='project_of'"), [("o/r",)])
        after["kv"] = [r for r in after["kv"] if r[1] not in ("project_of", "control", "project", "work_order", "throttle")]
        self.assertEqual(after, before)
        db.close()
        self.w.finish("b1", PR_LINE)
        self.tick(2)
        self.assertEqual(self.state(), "reviewing")

    def test_a_ledger_with_rows_and_no_project_is_refused_for_another_project(self):
        d = D.Dispatcher(self.cfg, self.w.account, self.w.gh, now=lambda: self.w.clock)
        with contextlib.redirect_stdout(self.out):
            d.once()
        d.close()
        shutil.copy(self.cfg["ledger_file"], self.p.ledger)
        db = sqlite3.connect(self.p.ledger)
        db.execute("DELETE FROM kv WHERE k='project_of'")
        db.commit()
        db.close()
        self.start()
        self.select("p/q")
        self.tick(4)
        self.assertEqual(self.d.active, "o/r")
        self.assertEqual(len(self.lines_said("holds rows and names no project")), 1)
        self.assertEqual(self.p.sends, [])

    def test_a_ledger_of_one_project_is_refused_for_another(self):
        path = os.path.join(self.dir.name, "x.db")
        s = S.Store(path)
        s.claim("a/b", "o/r")
        s.claim("a/b", "o/r")
        with self.assertRaises(S.Refused):
            s.claim("p/q", "o/r")
        s.close()
        with self.assertRaises(S.Refused):
            D.Dispatcher(dict(self.cfg, repo="p/q", home="o/r", ledger_file=path), self.w.account, self.w.gh)
        S.Store(path).close()

    def test_equal_issue_numbers_of_two_projects_do_not_collide(self):
        self.start()
        self.to_review()
        self.select("p/q")
        self.answer["work_order"]["issues"] = [5]
        self.widen()
        self.tick(2)
        self.assertEqual(self.d.active, "p/q")
        self.assertEqual(self.state(), "reviewing")
        self.assertEqual(self.p.rows("SELECT job, state FROM jobs"), [("5", "building")])
        self.assertEqual(self.w.rows("SELECT json_extract(data, '$.title') FROM jobs WHERE job='5'"), [("Fix x",)])
        self.assertEqual(self.p.rows("SELECT json_extract(data, '$.title'), json_extract(data, '$.repo') FROM jobs WHERE job='5'"), [("Other", "p/q")])
        self.assertEqual(self.p.rows("SELECT v FROM kv WHERE job='-' AND k='project_of'"), [("p/q",)])
        self.assertEqual(self.p.sends[0][0], "b1")

    def test_a_switch_lets_the_job_of_the_work_order_finish_and_sends_none_twice(self):
        self.w.issues += [issue(6, "Six"), issue(7, "Seven", deps="#6")]
        self.w.open_numbers.add(6)
        self.start()
        self.to_review()
        self.assertEqual([r[0] for r in self.w.rows("SELECT state FROM jobs ORDER BY job")], ["reviewing"])
        self.select("p/q")
        self.tick()
        self.w.issues.append(issue(8, "Eight"))
        self.tick()
        self.assertEqual(self.p.reports[-1]["repo"], "p/q")
        self.assertEqual(self.p.reports[-1]["finishing"], [{"repo": "o/r", "jobs": 1}])
        self.w.finish("r1", "ok\nVERDICT: ACCEPT @abcdef1")
        self.tick(2)
        self.w.workflows[HEAD] = [wf("ci", "success")]
        self.tick(4)
        self.assertEqual(self.w.rows("SELECT job, state FROM jobs ORDER BY job"), [("5", "merged")])
        self.assertEqual(len(self.w.merges), 1)
        self.assertEqual(self.w.cancels + self.p.cancels, [])
        firsts = [(a, m.split("\n")[0]) for a, m, _ in self.w.sends + self.p.sends]
        self.assertEqual(len(firsts), len(set(firsts)))
        self.assertFalse([m for _, m, _ in self.w.sends if "#7" in m.split("\n")[0] or "#8" in m.split("\n")[0]])
        self.assertEqual(self.p.reports[-1]["finishing"], [])
        self.assertEqual(self.p.rows("SELECT state FROM jobs WHERE job='5'"), [("building",)])
        self.p.finish(self.p.sends[0][0], PR_LINE)
        self.tick()
        self.select("o/r")
        self.tick(3)
        self.assertEqual(self.d.active, "o/r")
        self.assertIn("6", self.job_ids())

    def test_two_lines_never_use_the_same_coworker_at_once(self):
        self.start()
        self.to_review()
        self.select("p/q")
        self.answer["work_order"]["issues"] = [5]
        self.widen()
        self.tick(2)
        busy = [a for a, _ in self.d.lines["o/r"].own()]
        self.assertTrue(busy)
        self.assertNotIn(self.p.sends[0][0], busy)

    def test_the_app_away_keeps_the_last_project_also_after_a_restart(self):
        self.start()
        self.to_review()
        self.select("p/q")
        self.tick(2)
        self.w.report_answer = self.p.report_answer = None
        self.tick(3)
        self.assertEqual(self.d.active, "p/q")
        self.tick(2, fresh=True)
        self.assertEqual(self.d.active, "p/q")
        self.assertTrue(self.d.lines["p/q"].taking)
        self.assertFalse(self.d.lines["o/r"].taking)

    def test_a_malformed_answer_changes_nothing_and_is_one_problem_line(self):
        self.start()
        for bad in ("x", {"repo": "../x"}, {"repo": 7}, ["p/q"], {"name": "p/q"}):
            self.answer["project"] = bad
            self.tick(3)
            self.assertEqual(self.d.active, "o/r")
        self.assertEqual(len(self.lines_said("project answer not understood: the factory stays on o/r")), 1)
        self.assertEqual(self.p.sends, [])
        self.assertEqual(self.w.rows("SELECT COUNT(*) FROM events WHERE key='project' AND old != 'null'"), [(0,)])

    def test_a_project_whose_readiness_did_not_pass_here_is_refused_whatever_the_app_says(self):
        self.start(passed=False)
        self.select("p/q")
        self.tick(4)
        self.assertEqual(self.d.active, "o/r")
        self.assertEqual(len(self.lines_said("project p/q not taken: its readiness is not recorded as passed here")), 1)
        self.d.kv.set("-", "ready:p/q", json.dumps({"passed": False}))
        self.tick(2)
        self.assertEqual(self.d.active, "o/r")
        self.assertEqual(self.p.sends, [])

    def test_every_switch_is_one_line_in_the_ledger_with_who_and_when(self):
        self.start()
        self.select("p/q", by="rob@example.com")
        self.tick(3)
        self.select("o/r", by="rob@example.com")
        self.tick(3)
        rows = self.w.rows("SELECT old, new FROM events WHERE key='project' AND old != 'null' ORDER BY id")
        self.assertEqual([json.loads(r[0]) for r in rows], ["o/r", "p/q"])
        first = json.loads(json.loads(rows[0][1]))
        self.assertEqual((first["repo"], first["from"], first["by"]), ("p/q", "o/r", "rob@example.com"))
        self.assertRegex(first["at"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(self.w.reports[-1]["switch"]["repo"], "o/r")
        self.assertEqual(len(self.lines_said("#project o/r -> p/q by rob@example.com; finishing")), 1)

    def test_a_kill_between_the_project_and_its_events_row_is_repaired_at_the_restart(self):
        self.start()
        self.select("p/q")
        self.tick(2)
        self.w.report_answer = self.p.report_answer = None
        self.close()
        db = sqlite3.connect(self.cfg["ledger_file"])
        db.execute("DELETE FROM events WHERE key='project'")
        db.commit()
        db.close()
        self.tick(2, fresh=True)
        self.tick(2, fresh=True)
        self.assertEqual(self.d.active, "p/q")
        kv = self.w.rows("SELECT v FROM kv WHERE job='-' AND k='project'")[0][0]
        rows = self.w.rows("SELECT old, new FROM events WHERE key='project'")
        self.assertEqual([(json.loads(a), json.loads(b)) for a, b in rows], [("o/r", kv)])
        self.assertEqual(len(self.lines_said("the switch to p/q had no events row; it is written now")), 1)

    def test_a_home_ledger_of_another_project_stops_the_start_and_leaves_the_store_closed(self):
        s = S.Store(self.cfg["ledger_file"])
        s.claim("a/b", "a/b")
        s.close()
        with self.assertRaises(S.Refused) as got:
            self.new()
        self.assertEqual(str(got.exception), "the ledger ledger.db belongs to a/b, not to o/r")
        S.Store(self.cfg["ledger_file"]).close()
        self.assertEqual(self.w.sends, [])

    def test_who_made_the_switch_is_one_printable_line_of_at_most_100_characters(self):
        self.start()
        self.select("p/q", by="rob\n2026-11-19T00:00:00Z #- forged\x00" + "x" * 200, order=False)
        self.tick(3)
        saved = json.loads(self.w.rows("SELECT v FROM kv WHERE job='-' AND k='project'")[0][0])
        self.assertEqual(saved["by"], ("rob 2026-11-19T00:00:00Z #- forged " + "x" * 200)[:100])
        self.assertEqual(len(self.lines_said("forged")), 1)
        self.assertEqual(self.lines_said("forged"), self.lines_said("#project o/r -> p/q by rob 2026"))

    def test_the_dispatcher_started_by_main_is_the_lines_with_main_s_own_module(self):
        seen = []
        real = L.Lines
        for name, fake in (("settings", lambda: dict(self.cfg, proof=True)), ("make_account", lambda url, key: self.w.account),
                           ("make_gh", lambda tok: self.w.gh), ("read_secret", lambda path: "fake-key")):
            self.addCleanup(setattr, D, name, getattr(D, name))
            setattr(D, name, fake)
        self.addCleanup(setattr, L, "Lines", real)
        L.Lines = lambda *a, **k: seen.append(k) or real(*a, **k)
        self.seed()
        with unittest.mock.patch.dict(os.environ, {"DISPATCH_ACCOUNT_URL": "http://account.invalid"}), contextlib.redirect_stdout(self.out):
            self.assertEqual(D.main(["once"]), 0)
        self.assertIs(seen[0]["mod"], D)
        self.assertEqual(self.state(), "building")


class Ready:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        path = next(x for x in args[1:] if not x.startswith("-") and x not in ("POST", "DELETE"))
        if path == "repos/p/q":
            return json.dumps({"full_name": "p/q", "has_issues": True})
        if path == "repos/p/q/actions/workflows":
            return "Done-test red before green\n"
        return "abc123\n"


class Drain(Pair):
    def test_a_switch_lets_the_old_project_push_its_jobs_in_flight_before_the_first_job_of_the_new_one(self):
        self.cfg["project_owners"] = ["o", "p"]
        self.start(passed=False)
        self.d.gh = Ready()
        self.tick()
        self.assertEqual(self.state(), "building")
        self.answer["check"] = {"repo": "p/q", "at": D.iso(self.w.clock)}
        self.tick()
        self.assertIs(json.loads(self.w.rows("SELECT v FROM kv WHERE job='-' AND k='ready:p/q'")[0][0])["passed"], True)
        del self.answer["check"]
        self.w.clock += 5
        self.answer["project"] = {"repo": "p/q", "by": "rob", "at": D.iso(self.w.clock - 1)}
        self.answer["work_order"] = {"id": "pq", "repo": "p/q", "kind": "all_issues", "issues": [5], "by": "rob", "at": D.iso(self.w.clock)}
        self.widen()
        self.tick(3)
        self.assertEqual(self.d.active, "p/q")
        self.assertEqual(self.p.sends, [])
        self.w.issues.append(issue(9, "Nine"))
        self.tick(2)
        self.assertNotIn("9", self.job_ids())
        self.assertEqual(self.p.sends, [])
        self.w.finish("b1", PR_LINE)
        self.tick(3)
        self.assertEqual(self.state(), "reviewing")
        self.assertEqual(len(self.p.sends), 1)
        said = self.out.getvalue()
        order = [said.index(x) for x in ("#project o/r -> p/q", "pull request #", "#project p/q starts")]
        self.assertEqual(order, sorted(order))
        self.assertGreater(said.rindex("build -> "), order[-1])


class Rechecks(Pair):
    def pushes(self):
        return sum(1 for c in self.d.gh.calls if "POST" in c and any(x.endswith("/git/refs") for x in c))

    def test_one_fresh_click_is_one_check_and_neither_skew_nor_repeats_drive_more_writes(self):
        self.cfg["project_owners"] = ["o", "p"]
        self.start(passed=False)
        self.d.gh = Ready()
        self.w.clock = 1000.7
        self.answer["project"] = {"repo": "p/q", "by": "rob", "at": D.iso(1000.5, ms=True)}
        self.tick()
        self.assertEqual((self.d.active, self.pushes()), ("p/q", 1))
        self.assertEqual(len(self.lines_said("#project o/r -> p/q by rob")), 1)
        self.assertEqual(len(self.lines_said("readiness of p/q asked by rob: passed")), 1)
        self.select("o/r")
        self.tick()
        self.w.clock += 10
        self.answer["project"] = {"repo": "p/q", "by": "rob", "at": D.iso(self.w.clock, ms=True)}
        self.tick()
        self.assertEqual((self.d.active, self.pushes()), ("p/q", 1))
        self.select("o/r")
        self.tick()
        self.answer["check"] = {"repo": "p/q", "at": D.iso(self.w.clock + 7200, ms=True)}
        for _ in range(6):
            self.w.clock += 30
            self.tick()
        self.assertEqual(self.pushes(), 2)
        for n in range(40):
            self.w.clock += 61
            self.answer["check"] = {"repo": "p/q", "at": D.iso(self.w.clock, ms=True)}
            self.tick()
        self.assertLessEqual(self.pushes(), 2 + L.READINESS_PER_HOUR)
        self.assertEqual(len(self.lines_said("readiness checks per hour")), 1)


class Controls(Pair):
    def new(self):
        self.seed(control=False)
        return super().new()

    def run_on(self, conns, off=(), default="c1", down=(), unlisted=False):
        inner, self.unlisted, self.unknown, self.down = self.w.account, unlisted, False, set(down)

        def account(tool, args, timeout=30):
            if tool == "list_ai_connections":
                if self.unlisted:
                    raise D.Error("account list_ai_connections failed: TimeoutError")
                return {"connections": [{"id": c, "provider": "claude", "isDefault": c == default, "connected": c not in self.down, "signIn": None, "planLimits": None}
                                        for c in sorted({c for c in conns.values() if c} | {default})]}
            if tool == "get_agent":
                if self.unknown:
                    raise D.Error("account get_agent failed: TimeoutError")
                conn = conns.get(args["agentId"], "c1")
                return dict(inner(tool, args), runsOn={"connectionId": conn} if conn else None)
            return inner(tool, args)

        self.w.account = account
        if off:
            self.answer["providers"] = {"off": list(off), "by": "rob", "at": D.iso(self.w.clock)}

    def control(self, state):
        self.clicks = getattr(self, "clicks", 0) + 1
        self.answer["control"] = {"state": state, "by": "rob", "at": D.iso(self.w.clock + self.clicks)}

    def test_a_fresh_factory_is_paused_and_a_pause_starts_nothing_new_while_running_work_finishes(self):
        self.d = self.new()
        self.tick(3)
        self.assertEqual(self.w.sends, [])
        self.assertEqual(self.d.lines["o/r"].run_state, "PAUSED")
        self.control("RUNNING")
        self.tick(2)
        self.assertEqual((self.state(), len(self.w.sends)), ("building", 1))
        self.control("PAUSED")
        self.tick()
        self.w.finish("b1", PR_LINE)
        self.tick(3)
        self.assertEqual((self.state(), len(self.w.sends)), ("review_wait", 1))
        self.assertEqual(len(self.lines_said("#control RUNNING -> PAUSED by rob")), 1)
        self.assertIn("control PAUSED", self.d.lines["o/r"].beat_line)
        self.assertEqual(self.w.reports[-1]["control"]["state"], "PAUSED")

    def jobs_by_state(self):
        return sorted((j["issue"], j["state"]) for j in self.d.lines["o/r"].store.jobs())

    def waiting_job(self):
        self.d.lines["o/r"].store.put_job("6", "waiting", {"issue": 6, "title": "Six", "recheck": True, "rechecks": 1})

    def test_a_normal_stop_lets_the_running_step_finish_starts_no_follow_up_cancels_the_queue_and_ends_stopped(self):
        self.d = self.new()
        self.control("RUNNING")
        self.tick(2)
        self.assertEqual(self.state(), "building")
        self.waiting_job()
        self.control("DRAINING")
        for _ in range(2):
            self.tick()
            self.assertEqual(self.jobs_by_state(), [(5, "building"), (6, "cancelled")])
            self.assertEqual((len(self.w.sends), self.d.read("control", {})["state"]), (1, "DRAINING"))
        self.w.finish("b1", PR_LINE)
        self.tick()
        self.assertEqual((self.d.read("control", {})["state"], self.w.reports[-1]["control"]["state"]), ("STOPPED", "STOPPED"))
        self.tick(2)
        self.assertEqual((self.jobs_by_state(), len(self.w.sends), self.w.cancels), ([(5, "cancelled"), (6, "cancelled")], 1, []))
        self.assertEqual(self.w.rows("SELECT status FROM fires"), [("done",)])
        self.assertEqual(self.d.read("control", {})["state"], "STOPPED")
        self.assertEqual(len(self.lines_said("#control DRAINING -> STOPPED by factory")), 1)
        self.assertEqual(self.w.reports[-1]["control"]["state"], "STOPPED")
        self.assertEqual(self.d.lines["o/r"].store.failures(), [])
        self.control("RUNNING")
        self.tick(3)
        self.assertEqual((self.jobs_by_state(), len(self.w.sends)), ([(5, "cancelled"), (6, "cancelled")], 1))

    def test_an_idle_drain_is_reported_stopped_in_the_beat_it_is_learnt(self):
        self.d = self.new()
        self.waiting_job()
        self.control("DRAINING")
        self.tick()
        self.assertEqual((self.jobs_by_state(), self.w.sends), ([(5, "cancelled"), (6, "cancelled")], []))
        self.assertEqual((self.d.read("control", {})["state"], self.w.reports[-1]["control"]["state"]), ("STOPPED", "STOPPED"))

    def test_a_hard_stop_leaves_nothing_in_flight_and_nothing_queued_without_an_error(self):
        self.d = self.new()
        self.control("RUNNING")
        self.tick(2)
        self.assertEqual(self.state(), "building")
        self.waiting_job()
        self.control("STOPPED")
        self.tick()
        line = self.d.lines["o/r"]
        self.assertEqual(self.w.cancels, [(self.w.order[-1][1], self.w.order[-1][0])])
        self.assertEqual(self.jobs_by_state(), [(5, "cancelled"), (6, "cancelled")])
        self.assertEqual((self.w.rows("SELECT status FROM fires"), line.store.running(), line.store.pending()), ([("cancelled",)], [], []))
        self.assertEqual(line.store.failures(), [])
        self.control("RUNNING")
        self.tick(3)
        self.assertEqual((self.jobs_by_state(), len(self.w.sends)), ([(5, "cancelled"), (6, "cancelled")], 1))

    def test_a_hard_stop_ends_planner_and_station_work_cancelled_and_running_again_does_not_resume_it(self):
        self.d = self.new()
        line = self.d.lines["o/r"]
        for job, stage, agent, run in (("plan:7", "review", "p1", "pr1"), ("accept:8", "accept", "r1", "ar1"), ("9", "resolve", "x1", "rr1")):
            line.store.fired(line.store.intent(job, "", stage, coworker=agent), run)
            self.w.runs[run] = {"status": "running"}
        line.store.set_many("plan:7", (("state", "reviewing"), ("agent", "p1"), ("copy", "1"), ("run", "pr1"), ("lens", "0"), ("started", "2026-11-23T00:00:00Z")))
        line.store.set_many("plan:10", (("state", "unsent"),))
        line.store.set_many("accept:8", (("state", "running"), ("agent", "r1"), ("copy", 1), ("run", "ar1"), ("sends", 1), ("started", self.w.clock)))
        line.store.set_many("accept:11", (("state", "unsent"),))
        line.store.set(R.KV, "dev red", json.dumps({"state": "resolving", "issue": 9, "agent": "x1", "copy": 1, "run": "rr1", "sends": 1, "sent_at": self.w.clock}))
        line.store.set(R.KV, "disk", json.dumps({"state": "resolve_wait", "issue": 12, "sends": 0}))
        self.control("STOPPED")
        self.tick()
        self.assertEqual(sorted(self.w.cancels), [("p1", "pr1"), ("r1", "ar1"), ("x1", "rr1")])
        self.assertEqual(self.w.rows("SELECT DISTINCT status FROM fires"), [("cancelled",)])

        def ended():
            problems = line.store.get_all(R.KV)
            return ([line.store.get_all(k)["state"] for k in ("plan:7", "plan:10", "accept:8", "accept:11")]
                    + [json.loads(problems[k])["state"] for k in ("dev red", "disk")])

        self.assertEqual(ended(), ["cancelled"] * 6)
        self.assertEqual(line.store.failures(), [])
        self.control("RUNNING")
        self.tick(3)
        self.assertEqual((ended(), len(self.w.sends)), (["cancelled"] * 6, 0))

    def test_an_off_connection_is_never_fired_and_its_work_goes_to_a_coworker_on_an_enabled_one(self):
        self.w.issues.append(issue(6, "Six"))
        self.w.open_numbers.add(6)
        self.run_on({"b1": "c1", "b2": "c2", "r1": "c2", "r2": "c2"}, off=["c1"])
        self.d = self.new()
        self.control("RUNNING")
        self.tick(4)
        self.assertEqual([a for a, _, _ in self.w.sends], ["b2"])
        self.assertNotIn("connectionId", self.w.send_args[-1])
        self.assertEqual(self.w.reports[-1]["providers"]["off"], ["c1"])

    def test_with_every_connection_off_jobs_wait_for_an_enabled_provider(self):
        self.run_on({"b1": "c1", "b2": "c2"}, off=["c1", "c2"])
        self.d = self.new()
        self.control("RUNNING")
        self.tick(4)
        self.assertEqual(self.w.sends, [])
        self.assertEqual(self.state(), "queued")
        self.assertEqual(self.d.lines["o/r"].store.get_job("5")["wait_reason"], "no enabled provider")

    def failing_over(self, **kw):
        self.run_on({"b1": "95h6", "b2": "95h6", "r1": "95h6", "r2": "95h6"}, off=kw.pop("off", ["95h6"]), default="opus", **kw)
        self.d = self.new()
        self.control("RUNNING")
        self.tick(4)

    def test_a_coworker_whose_connection_is_off_runs_on_the_default_picked_under_providers(self):
        self.failing_over()
        self.assertEqual((self.state(), len(self.w.sends)), ("building", 1))
        self.assertEqual(self.w.send_args[-1]["connectionId"], "opus")
        self.assertIn(self.w.send_args[-1]["agentId"], ("b1", "b2"))
        self.assertTrue(any("on default opus, its own connection is off" in line for line in self.lines_said("on default")))

    def test_with_the_default_off_too_the_work_waits_and_nothing_is_sent(self):
        self.failing_over(off=["95h6", "opus"])
        self.assertEqual((self.w.sends, self.state()), ([], "queued"))
        self.assertEqual(self.d.lines["o/r"].store.get_job("5")["wait_reason"], "no enabled provider")

    def test_a_default_that_is_not_connected_is_never_used(self):
        self.failing_over(down=["opus"])
        self.assertEqual((self.w.sends, self.state()), ([], "queued"))
        self.assertEqual(self.d.lines["o/r"].store.get_job("5")["wait_reason"], "no enabled provider")

    def recovers_once(self, why, fix, pinned="opus"):
        self.assertEqual((self.w.sends, self.state()), ([], "queued"))
        self.assertEqual(self.d.lines["o/r"].store.get_job("5")["wait_reason"], why)
        fix()
        self.tick(4)
        self.assertEqual((self.state(), len(self.w.sends), self.w.send_args[-1].get("connectionId")), ("building", 1, pinned))
        self.tick(4)
        self.assertEqual(len(self.w.sends), 1)

    def test_an_unreadable_connection_list_launches_nothing_until_it_reads_again(self):
        self.failing_over(unlisted=True)
        self.recovers_once(D.ROUTE_UNREADABLE, lambda: setattr(self, "unlisted", False))

    def test_an_unreadable_coworker_connection_launches_nothing_until_it_reads_again(self):
        self.run_on({"b1": "95h6", "b2": "95h6", "r1": "95h6", "r2": "95h6"}, off=["95h6"], default="opus")
        self.unknown = True
        self.d = self.new()
        self.control("RUNNING")
        self.tick(4)
        self.recovers_once(D.ROUTE_UNKNOWN, lambda: setattr(self, "unknown", False))

    def test_no_own_choice_and_a_default_that_is_not_connected_launches_nothing_until_it_connects(self):
        self.run_on({"b1": None, "b2": None, "r1": None, "r2": None}, default="opus", down=["opus"])
        self.d = self.new()
        self.control("RUNNING")
        self.tick(4)
        self.recovers_once(D.NO_PROVIDER, self.down.clear, pinned=None)

    def test_a_route_the_engine_refuses_four_times_holds_the_work_and_launches_once_when_it_can_run(self):
        refusing, refused = [True], []
        why = {"error": "The coworker could not be reached: 503 " + json.dumps({"error": "No connection can run this coworker now: opus cannot run "
               "claude-opus-5-5, and the default picked under Providers cannot either. It runs once one of them is connected again."})}

        def opener(req, timeout):
            refused.append(json.loads(req.data)["params"]["arguments"]["agentId"])
            return io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(why)}], "isError": True}}).encode())

        engine = D.make_account("https://acct.example/mcp", "k", opener)
        self.run_on({"b1": "95h6", "b2": "95h6", "r1": "95h6", "r2": "95h6"}, off=["95h6"], default="opus")
        listed = self.w.account
        self.w.account = lambda tool, args, **kw: engine(tool, args) if tool == "send_message" and refusing else listed(tool, args, **kw)
        self.d = self.new()
        self.control("RUNNING")
        for _ in range(40):
            if len(refused) >= 4:
                break
            self.tick()
            self.w.clock += 300
        refusing.clear()
        self.tick(4)
        self.assertEqual((len(refused), self.state(), [a.get("connectionId") for a in self.w.send_args]), (4, "building", ["opus"]))
        self.assertFalse(self.d.lines["o/r"].store.retries("5", "transient"))
        self.tick(4)
        self.assertEqual(len(self.w.sends), 1)

    def test_an_off_coworker_is_never_sent_by_a_replan_a_resend_or_a_direct_send(self):
        self.cfg["types"] = {"coder": {"coworkers": self.cfg["builders"]}, "reviewer": {"coworkers": self.cfg["reviewers"]},
                             "planner": {"coworkers": [{"id": "p1", "name": "Boss"}]}}
        self.failing_over(unlisted=True)
        line = self.d.lines["o/r"]
        self.assertEqual(line.cfg["off_agents"], ["b1", "b2", "p1", "r1", "r2"])
        with contextlib.redirect_stdout(self.out):
            j = line.store.get_job("5")
            line.replan(dict(j, reason="plan: too wide"))
            j.update(state="building", agent="b1", attempt=1, sending_step="build", copy=1)
            line.failed_attempt(j, "boom", "ended")
            self.assertEqual((j["state"], j["retry_attempt"], j["attempt"]), (D.BACK["building"], 2, 1))
            self.assertEqual(self.lines_said("not sent"), [])
            line.send(j, "b1", "build", "go", "building")
        self.assertEqual(self.w.sends, [])
        self.assertEqual(len(self.lines_said("build not sent: " + D.ROUTE_UNREADABLE)), 1)

    def test_an_own_connection_that_is_not_connected_runs_on_the_default(self):
        self.failing_over(off=[], down=["95h6"])
        self.assertEqual((self.state(), len(self.w.sends), self.w.send_args[-1]["connectionId"]), ("building", 1, "opus"))

    def test_once_the_default_is_on_again_the_waiting_work_is_sent_once(self):
        self.failing_over(off=["95h6", "opus"])
        self.answer["providers"] = {"off": ["95h6"], "by": "rob", "at": D.iso(self.w.clock)}
        self.tick(4)
        self.assertEqual((self.state(), len(self.w.sends), self.w.send_args[-1]["connectionId"]), ("building", 1, "opus"))
        self.tick(4)
        self.assertEqual(len(self.w.sends), 1)


class WorkOrders(Pair):
    def order(self, kind, issues, repo="o/r"):
        self.answer["work_order"] = {"id": "wo-%d" % len(self.w.reports), "repo": repo, "kind": kind, "issues": issues, "by": "rob", "at": D.iso(self.w.clock)}

    def running_factory(self):
        self.d = self.new()
        self.d.kv.set("-", "control", json.dumps({"state": "RUNNING", "by": "test", "at": "2026-11-23T00:00:00Z"}))

    def test_nothing_is_picked_up_without_an_owner_chosen_project_and_a_work_order(self):
        self.running_factory()
        self.tick(3)
        self.assertEqual((self.w.sends, self.d.lines["o/r"].store.jobs()), ([], []))
        self.assertEqual(self.w.reports[-1]["work_order"]["wait"], "no project chosen")
        self.select("o/r", order=False)
        self.tick(3)
        self.assertEqual((self.w.sends, self.d.lines["o/r"].store.jobs()), ([], []))
        self.assertEqual(self.w.reports[-1]["work_order"]["wait"], "no work order")
        self.order("issue", [5])
        self.tick(3)
        self.assertEqual((self.state(), len(self.w.sends)), ("building", 1))
        self.assertEqual({k: self.w.reports[-1]["work_order"][k] for k in ("kind", "issues", "current", "done", "wait")},
                         {"kind": "issue", "issues": [5], "current": 5, "done": [], "wait": None})

    def test_all_issues_run_one_at_a_time_in_the_order_given(self):
        self.w.issues.append(issue(6, "Six"))
        self.w.open_numbers.add(6)
        self.running_factory()
        self.select("o/r")
        self.order("all_issues", [6, 5])
        self.tick(4)
        line = self.d.lines["o/r"]
        self.assertEqual([(j["issue"], j["state"]) for j in line.store.jobs()], [(6, "building")])
        self.assertEqual(len(self.w.sends), 1)
        six = line.store.get_job("6")
        line.store.put_job("6", "merged", dict(six, state="merged", relabelled=True, commented=True))
        self.tick(4)
        self.assertEqual(sorted((j["issue"], j["state"]) for j in line.store.jobs()), [(5, "building"), (6, "merged")])
        self.assertEqual(len(self.w.sends), 2)
        self.assertEqual({k: self.w.reports[-1]["work_order"][k] for k in ("current", "done")}, {"current": 5, "done": [6]})


class OrderRules(Pair):
    order = WorkOrders.order
    running_factory = WorkOrders.running_factory

    def ready_order(self, kind, issues):
        self.running_factory()
        self.select("o/r", order=False)
        self.order(kind, issues)

    def act(self, action, n):
        self.answer["work_order_action"] = {"action": action, "order_id": self.answer["work_order"]["id"], "issue": n, "by": "rob", "at": D.iso(self.w.clock)}

    def order_jobs(self):
        return sorted((j["issue"], j["state"]) for j in self.d.lines["o/r"].store.jobs())

    def block(self, n):
        line = self.d.lines["o/r"]
        j = line.store.get_job(str(n))
        line.store.put_job(str(n), "blocked", dict(j, state="blocked", relabelled=True, commented=True, reason="x", sending=None))

    def test_an_issue_of_the_order_needs_no_label_but_waits_while_its_body_is_not_cut_shaped(self):
        self.w.unlabelled.add(5)
        self.w.issues.append({"number": 6, "title": "Six", "body": "just some words", "comments": []})
        self.ready_order("issue", [6])
        self.tick(3)
        self.assertEqual((self.order_jobs(), self.w.reports[-1]["work_order"]["wait"]), ([], "issue #6 body is not cut-shaped"))
        self.assertEqual(self.w.reports[-1]["work_order"]["current"], 6)
        self.order("issue", [5])
        self.tick(3)
        self.assertEqual(self.order_jobs(), [(5, "building")])

    def test_both_stops_cancel_the_work_order(self):
        self.ready_order("all_issues", [5])
        self.tick(2)
        self.control("DRAINING")
        self.tick(2)
        self.assertEqual((self.w.reports[-1]["work_order"]["kind"], self.w.reports[-1]["work_order"]["wait"]), (None, "no work order"))
        self.order("issue", [5])
        self.control("STOPPED")
        self.tick(2)
        self.assertEqual((self.w.reports[-1]["work_order"]["kind"], self.w.reports[-1]["work_order"]["wait"]), (None, "no work order"))
        self.assertEqual(len(self.lines_said("cancelled by the stop")), 2)

    def control(self, state):
        self.clicks = getattr(self, "clicks", 0) + 1
        self.answer["control"] = {"state": state, "by": "rob", "at": D.iso(self.w.clock + self.clicks)}

    def stop_readd_start(self, stop, stage):
        self.ready_order("all_issues", [5])
        self.tick(2)
        self.control(stop)
        self.tick(2)
        if stop == "DRAINING":
            self.w.finish("b1", PR_LINE)
            self.tick()
        self.assertEqual((self.order_jobs(), self.d.read("control", {})["state"]), ([(5, "cancelled")], "STOPPED"))
        churn = lambda: (len(self.lines_said("#5 queued")), len(self.lines_said("#5 cancelled: the factory was stopped")))
        before, sends = churn(), len(self.w.sends)
        self.order("all_issues", [5])
        self.tick(3)
        self.assertEqual((churn(), len(self.w.sends), self.order_jobs()), (before, sends, [(5, "cancelled")]))
        self.control("RUNNING")
        self.tick(4)
        wo = self.w.reports[-1]["work_order"]
        self.assertEqual((wo["current"], wo["done"], wo["wait"]), (5, [], None))
        self.assertEqual((len(self.w.sends), self.order_jobs(), self.d.lines["o/r"].store.get_job("5")["takes"]), (sends + 1, [(5, stage)], 1))

    def test_after_a_hard_stop_a_re_added_issue_is_taken_once_on_start(self):
        self.stop_readd_start("STOPPED", "building")

    def test_after_a_normal_stop_a_re_added_issue_is_taken_once_on_start(self):
        self.stop_readd_start("DRAINING", "reviewing")

    def test_a_failed_job_halts_the_sequence_until_the_owner_retries_or_skips_it(self):
        self.w.issues.append(issue(6, "Six"))
        self.w.open_numbers.add(6)
        self.ready_order("all_issues", [5, 6])
        self.tick(3)
        self.block(5)
        self.tick(3)
        self.assertEqual((self.order_jobs(), self.w.reports[-1]["work_order"]["wait"]), ([(5, "blocked")], "job #5 failed: retry or skip"))
        self.act("retry", 5)
        self.tick(3)
        self.assertEqual(self.order_jobs(), [(5, "building")])
        self.assertEqual(self.d.lines["o/r"].store.get_job("5")["take"], 2)
        self.block(5)
        self.tick(3)
        self.assertEqual(self.w.reports[-1]["work_order"]["wait"], "job #5 failed: retry or skip")
        self.act("skip", 5)
        self.tick(3)
        self.assertEqual(self.order_jobs(), [(5, "blocked"), (6, "building")])
        self.assertEqual(self.w.reports[-1]["work_order"]["skipped"], [5])

    def test_all_issues_skips_an_issue_labelled_factory_paused(self):
        self.w.issues[0]["labels"] = ["factory", "factory-paused"]
        self.w.issues.append(dict(issue(6, "Six"), labels=["factory"]))
        self.w.open_numbers.add(6)
        self.ready_order("all_issues", [5, 6])
        self.tick(4)
        self.assertEqual(self.order_jobs(), [(6, "building")])

    def test_a_second_pick_of_an_issue_with_an_open_pull_request_takes_that_pull_request_up_again(self):
        self.w.open_prs = [{"number": 42, "title": "Fix x (#5)", "headRefName": "chunk/5-a", "author": {"login": "app/moldwright-factory"}, "isCrossRepository": False}]
        self.ready_order("issue", [5])
        self.tick(3)
        line = self.d.lines["o/r"]
        self.assertEqual([(j["issue"], j.get("pr")) for j in line.store.jobs()], [(5, 42)])
        self.assertFalse([a for a, _, _ in self.w.sends if a.startswith("b")])

    def test_only_a_factory_pull_request_on_its_chunk_branch_in_this_repo_is_taken_up(self):
        me = {"login": "app/moldwright-factory"}
        self.w.open_prs = [
            {"number": 41, "title": "Fix x (#5)", "headRefName": "chunk/5-a", "author": me, "isCrossRepository": True, "body": "fixes #5"},
            {"number": 42, "title": "Fix x (#5)", "headRefName": "chunk/5-b", "author": {"login": "stranger"}, "isCrossRepository": False, "body": "fixes #5"},
            {"number": 43, "title": "Fix x (#5)", "headRefName": "fix-5", "author": me, "isCrossRepository": False, "body": "fixes #5"},
            {"number": 44, "title": "Other", "headRefName": "chunk/5-c", "author": me, "isCrossRepository": False, "body": ""}]
        self.ready_order("issue", [5])
        self.tick(3)
        self.assertEqual([(j["issue"], j.get("pr")) for j in self.d.lines["o/r"].store.jobs()], [(5, 44)])

    def test_each_unlabelled_order_issue_is_viewed_once_within_five_minutes(self):
        self.w.issues += [issue(6, "Six"), issue(7, "Seven")]
        self.w.unlabelled.update({5, 6, 7})
        self.running_factory()
        line = self.d.lines["o/r"]
        line.work = {"wait": None, "issues": [5, 6, 7], "order": [5, 6, 7], "done": []}
        views = lambda: sum(1 for a in self.w.gh_calls if a[:2] == ["issue", "view"] and "number,title,labels,body,author,state" in a)
        with contextlib.redirect_stdout(self.out):
            line.order_issues([])
            first = views()
            self.w.clock += 30
            line.order_issues([])
        self.assertEqual((first, views() - first), (3, 0))

    def test_clearing_the_queue_cancels_only_pending_jobs_and_they_stay_out_of_the_next_intake(self):
        for n in (6, 7, 8):
            self.w.issues.append(issue(n, "N%d" % n))
            self.w.open_numbers.add(n)
        self.ready_order("all_issues", [5, 6, 7])
        self.tick(3)
        line = self.d.lines["o/r"]
        five = line.store.get_job("5")
        for n, state, extra in ((6, "queued", {}), (7, "waiting", {}), (8, "queued", {"sending": "build"})):
            line.store.put_job(str(n), state, dict(five, issue=n, title="N%d" % n, state=state, run=None, agent=None, **dict({"sending": None}, **extra)))
        self.answer["queue_clear"] = {"id": "qc-1", "repo": "o/r", "issues": [5, 6, 7, 8, 9], "by": "rob", "at": D.iso(self.w.clock)}
        sends = len(self.w.sends)
        self.tick(4)
        self.assertEqual(self.order_jobs(), [(5, "building"), (6, "cancelled"), (7, "cancelled"), (8, "queued")])
        self.assertEqual({k: self.w.reports[-1]["queue_clear"][k] for k in ("cleared", "kept")}, {"cleared": [6, 7], "kept": [5, 8, 9]})
        self.assertEqual((self.w.reports[-1]["work_order"]["skipped"], len(self.w.sends) - sends), ([6, 7], 0))
        self.assertEqual(len(self.lines_said("queue cleared in o/r")), 1)
        report = lambda: {k: self.w.reports[-1]["queue_clear"][k] for k in ("id", "outcome", "cleared", "kept")}
        self.assertEqual(report(), {"id": "qc-1", "outcome": "cleared", "cleared": [6, 7], "kept": [5, 8, 9]})
        self.w.clock += 1
        self.answer["queue_clear"] = {"id": "qc-2", "repo": "o/x", "issues": [8], "by": "rob", "at": D.iso(self.w.clock)}
        self.tick(2)
        self.assertEqual(report(), {"id": "qc-2", "outcome": "wrong_project", "cleared": [], "kept": []})
        self.w.clock += 1
        self.answer["queue_clear"] = {"id": "qc-3", "repo": "o/r", "issues": [8], "by": "rob", "at": D.iso(self.w.clock)}
        self.w.clock += 91
        self.tick(2)
        self.assertEqual(report(), {"id": "qc-3", "outcome": "expired", "cleared": [], "kept": []})
        jobs = self.order_jobs()
        self.answer["queue_clear"] = {"id": "qc-4", "repo": "o/r", "issues": [8], "by": "rob", "at": D.iso(self.w.clock - 100)}
        self.tick(2)
        self.assertEqual((report()["id"], self.order_jobs()), ("qc-3", jobs))

class Seats(unittest.TestCase):
    def test_the_pool_caps_all_stations_together_and_each_station_stays_within_its_seats(self):
        seats = {"code": 5, "LINUS": 6, "Boss": 2, "HOUSE": 1}
        types = {t: {"coworkers": [{"id": n.lower(), "name": n, "runs": 1}]} for t, n in zip(("coder", "reviewer", "planner", "resolver"), seats)}
        members = {n: {n.lower()} for n in seats}
        for pool, most in ((16, 14), (3, 3)):
            ghosts = []
            cfg = {"types": types, "pool": {"max": pool, "seats": seats, "members": members, "ghosts": lambda: ghosts}}
            started = True
            while started:
                started = False
                for t in types:
                    got = pools.pick_copy(cfg, t, ghosts)
                    if got:
                        ghosts.append(got)
                        started = True
            per = {s: sum(1 for a, _ in ghosts if a in members[s]) for s in seats}
            self.assertEqual(len(ghosts), most)
            self.assertTrue(all(per[s] <= seats[s] for s in seats), per)


class Throttle(Pair):
    order = WorkOrders.order
    running_factory = WorkOrders.running_factory

    def test_a_throttle_answer_sets_the_pool_and_seats_once_within_the_ceiling(self):
        self.running_factory()
        self.select("o/r", order=False)
        self.answer["throttle"] = {"max_ghosts": 16, "stations": {"B1": 5, "R1": 40}, "by": "rob", "at": "2026-11-23T21:00:00Z"}
        with unittest.mock.patch.dict(os.environ, {"FACTORY_MAX_GHOSTS": "12"}):
            self.tick(3)
        pool = self.d.lines["o/r"].cfg["pool"]
        self.assertEqual((pool["max"], pool["seats"]), (12, {"B1": 5, "B2": 1, "R1": 12, "R2": 1}))
        got = self.w.reports[-1]["throttle"]
        self.assertEqual((got["max_ghosts"], got["max_ghosts_ceiling"], got["ghosts_running"], got["stations"]["B1"]), (12, 12, 0, {"max": 5, "running": 0}))
        self.assertEqual(len(self.lines_said("pool 12")), 1)

    def test_a_spaced_station_name_is_taken_and_unknown_or_bad_keys_are_ignored(self):
        self.cfg["reviewers"][1]["name"] = "Scope Shaper"
        self.running_factory()
        self.select("o/r", order=False)
        self.answer["throttle"] = {"max_ghosts": 6, "stations": {"Scope Shaper": 3, "B1": 2, "nobody": 4, "B2": -1}, "by": "rob", "at": "2026-11-23T21:00:00.123Z"}
        self.tick(3)
        pool = self.d.lines["o/r"].cfg["pool"]
        self.assertEqual((pool["max"], pool["seats"]), (6, {"B1": 2, "B2": 1, "R1": 1, "Scope Shaper": 3}))
        self.assertEqual(self.w.reports[-1]["throttle"]["stations"]["Scope Shaper"], {"max": 3, "running": 0})
        self.assertEqual(self.lines_said("throttle answer not understood"), [])

    def test_a_throttle_with_an_unreadable_at_is_refused(self):
        self.running_factory()
        self.select("o/r", order=False)
        self.answer["throttle"] = {"max_ghosts": 6, "stations": {}, "by": "rob", "at": "soon"}
        self.tick(3)
        self.assertEqual(self.d.lines["o/r"].cfg["pool"]["max"], 1)
        self.assertEqual(len(self.lines_said("throttle answer has no readable at")), 1)

    def test_the_filing_error_scrubs_stateless_and_url_encoded_tokens(self):
        jwt = "eyJhbGciOiJSUzI1NiJ9." + "a-b_c" * 40 + ".sig-nat_ure"
        text = "HTTP 401 for ghs_12345678_%s, ghs%%5F12345678%%5F%s and x-access-token:ghp_abcdefgh123@github.com" % (jwt, jwt)
        got = L.scrub(text)
        for part in ("12345678", "eyJ", "a-b_c", "sig-nat", "ghp_abc"):
            self.assertNotIn(part, got)
        self.assertIn("HTTP 401 for [token]", got)

    def test_a_feature_order_files_its_issue_once_and_then_runs_it(self):
        made, real = [], self.w.gh

        def gh(args):
            a = list(args)
            if a[:2] == ["issue", "create"]:
                n = 70 + len(made)
                made.append(a)
                self.w.issues.append({"number": n, "title": a[a.index("--title") + 1], "body": a[a.index("--body") + 1], "comments": [], "labels": ["factory"]})
                return "https://github.com/o/r/issues/%d\n" % n
            if a[:2] == ["issue", "list"] and "--search" in a and any("Factory work order" in x for x in a):
                return "[]"
            return real(a)

        self.w.gh = gh
        self.running_factory()
        self.select("o/r", order=False)
        self.answer["work_order"] = {"id": "wo-f", "repo": "o/r", "kind": "feature", "text": "Add a thing\n" + ready(), "by": "rob", "at": D.iso(self.w.clock)}
        self.tick(4)
        self.tick(2, fresh=True)
        self.assertEqual(len(made), 1)
        self.assertEqual((made[0][made[0].index("--title") + 1], made[0][made[0].index("--label") + 1]), ("Add a thing", "factory"))
        self.assertEqual(sorted((j["issue"], j["state"]) for j in self.d.lines["o/r"].store.jobs()), [(70, "building")])
        self.assertEqual(self.w.reports[-1]["work_order"]["current"], 70)

    def test_a_work_order_runs_as_many_issues_at_once_as_the_pool_allows(self):
        self.running_factory()
        self.w.issues = [issue(n, "Fix %d" % n) for n in (5, 6, 7, 8)]
        self.select("o/r", order=False)
        self.order("all_issues", [5, 6, 7, 8])
        self.answer["throttle"] = {"max_ghosts": 3, "stations": {"B1": 2, "B2": 2}, "by": "rob", "at": D.iso(self.w.clock)}
        self.tick(4)
        building = [j["issue"] for j in self.d.lines["o/r"].store.jobs() if j["state"] == "building"]
        self.assertEqual(sorted(building), [5, 6, 7])

    def test_a_resent_old_stop_never_cancels_a_newer_work_order(self):
        self.running_factory()
        self.select("o/r", order=False)
        stop = {"state": "STOPPED", "by": "rob", "at": "2026-11-23T10:00:00Z"}
        self.answer["control"] = stop
        self.tick(2)
        self.answer["control"] = {"state": "RUNNING", "by": "rob", "at": "2026-11-23T10:05:00Z"}
        self.tick(2)
        self.answer["work_order"] = {"id": "wo-new", "repo": "o/r", "kind": "issue", "issues": [5], "by": "rob", "at": "2026-11-23T10:10:00Z"}
        self.tick(2)
        self.d.kv.set("-", "control_asked", "{}")
        self.answer["control"] = stop
        self.tick(2)
        got = self.w.reports[-1]
        self.assertEqual((got["control"]["state"], got["work_order"]["id"], got["work_order"]["kind"]), ("RUNNING", "wo-new", "issue"))



class Report(Pair):
    order = WorkOrders.order
    running_factory = WorkOrders.running_factory

    def test_an_oversize_report_is_trimmed_under_the_cap_and_sent(self):
        import snapshot
        self.running_factory()
        self.select("o/r", order=False)
        self.order("all_issues", list(range(1, 201)))
        store = self.d.lines["o/r"].store
        live = []
        for n in range(1000, 1300):
            title = ("Überprüfung – 修正 der Fabrik %d " % n) * 12 if n == 1002 else "T%d " % n + "t" * 250
            data = {"issue": n, "title": title, "body": "**Depends on**: none\n", "reason": "r" * 300, "wait_reason": "w" * 300}
            for i in range(30):
                store.put_job(str(n), "building" if i % 2 == 0 else "review_wait", data, "h" * 300, at="2026-11-23T00:%02d:%02dZ" % (n % 60, i))
            if n % 3:
                store.put_job(str(n), "merged", data, "m" * 300, at="2026-11-23T01:%02d:00Z" % (n % 60))
            else:
                live.append(n)
            for k in range(12):
                fid = store.intent(str(n), "", "build", coworker="B1")
                store.fired(fid, "run-%d-%d-%s" % (n, k, "a" * 40))
                store.close_run("run-%d-%d-%s" % (n, k, "a" * 40), "done", tokens_in=1, tokens_out=1)
        self.d.repos = ["special-place-ai-heaven/repo-%03d-%s" % (i, "q" * 150) for i in range(300)]
        self.d.repos_at = self.w.clock
        line = {"name": "n" * 40, "ok": False, "why": "y" * 500}
        for i in range(20):
            self.d.kv.set("-", "ready:special-place-ai-heaven/r%02d" % i, json.dumps({"passed": False, "lines": [line] * 20, "at": "2026-11-23T00:00:00.000Z"}))
        sent = len(self.w.reports)
        self.tick(2)
        self.assertGreater(len(self.w.reports), sent)
        got = self.w.reports[-1]
        self.assertEqual(snapshot.MAX_BYTES, 200 * 1024)
        self.assertLessEqual(len(json.dumps(got, separators=(",", ":"), ensure_ascii=False).encode("utf-8")), snapshot.MAX_BYTES)
        self.assertEqual(sorted(j["issue"] for j in got["jobs"] if j["state"] != "merged"), live)
        for key in ("version", "madeAt", "beat", "repo", "jobs", "holds", "pools", "endedToday", "control"):
            self.assertIn(key, got)

if __name__ == "__main__":
    unittest.main()
