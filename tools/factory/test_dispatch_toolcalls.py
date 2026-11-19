import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as S
import test_dispatch as T

D = T.D
FIRE = "SELECT shell_calls, read_calls, sleep_calls, tools_read FROM fires WHERE run_id=?"


def shell(cmd):
    return {"step": 1, "tool": "mcp__rerun__shell_exec", "input": json.dumps({"command": cmd, "timeoutMs": 120000}),
            "result": "ok", "isError": False, "durationMs": 10}


CALLS = [shell("cat a/b.py"), shell("grep -rn x a; sed -n 1,5p a/b.py"), shell("sleep 60; /data/tools/bin/ci-wait rerun 42"),
         shell("cd a && python3 -I -m unittest test_b"),
         {"step": 5, "tool": "mcp__rerun__fs_edit", "input": "{}", "result": "ok", "isError": False, "durationMs": 3}]


class Sweep(T.Base):
    def finished(self, calls=None):
        self.w.finish("b1", T.PR_LINE)
        rid = [r for r, a in self.w.order if a == "b1"][-1]
        if calls is not None:
            self.w.runs[rid]["toolCalls"] = calls
        return rid

    def failing(self, error):
        asked = []
        inner = self.d.account

        def account(tool, args):
            if tool == "get_run" and args.get("includeToolCalls"):
                asked.append(args["runId"])
                raise D.Error(error)
            return inner(tool, args)
        self.d.account = account
        return asked

    def test_a_build_run_is_counted_once_and_no_command_text_is_kept(self):
        self.tick()
        rid = self.finished(CALLS)
        self.tick(3)
        self.assertEqual(self.w.rows(FIRE, rid), [(4, 2, 1, "ok")])
        self.assertEqual(self.out.getvalue().count("tools of run %s: 4 shell calls, 2 only read, 1 slept" % rid), 1)
        for table in ("fires", "failures", "kv"):
            self.assertNotIn("ci-wait", repr(self.w.rows("SELECT * FROM %s" % table)))

    def test_an_account_error_gets_two_tries(self):
        self.tick()
        asked = self.failing("account get_run failed: the tool reported an error")
        rid = self.finished(CALLS)
        self.tick(2)
        self.assertEqual((self.w.rows(FIRE, rid)[0][3], len(asked)), (None, 1))
        self.tick()
        self.assertEqual((self.w.rows(FIRE, rid)[0][3], len(asked)), ("refused", 2))
        self.tick(3)
        self.assertEqual(len(asked), 2)

    def test_any_other_failure_gets_five_tries(self):
        self.tick()
        asked = self.failing("account get_run failed: TimeoutError")
        rid = self.finished(CALLS)
        self.tick(5)
        self.assertEqual((self.w.rows(FIRE, rid)[0][3], len(asked)), (None, 4))
        self.tick()
        self.assertEqual((self.w.rows(FIRE, rid)[0][3], len(asked)), ("refused", 5))
        self.tick(3)
        self.assertEqual(len(asked), 5)

    def test_an_answer_without_tool_calls_is_none(self):
        self.tick()
        rid = self.finished()
        self.tick(3)
        self.assertEqual(self.w.rows(FIRE, rid), [(None, None, None, "none")])

    def test_runs_that_ended_long_before_counting_began_are_not_read(self):
        self.tick()
        self.d.store.set("-", "tools_since", "2999-01-01T00:00:00Z")
        asked = []
        inner = self.d.account

        def account(tool, args):
            if args.get("includeToolCalls"):
                asked.append(args["runId"])
            return inner(tool, args)
        self.d.account = account
        rid = self.finished(CALLS)
        self.tick(3)
        self.assertEqual((self.w.rows(FIRE, rid)[0][3], asked), (None, []))

    def test_runs_inside_the_window_before_counting_began_are_read(self):
        self.tick()
        self.d.store.set("-", "tools_since", "2000-01-01T00:00:00Z")
        rid = self.finished(CALLS)
        self.tick(3)
        self.assertEqual(self.w.rows(FIRE, rid)[0][3], "ok")


class Seen(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.s = S.Store(os.path.join(d.name, "l.db"))
        self.addCleanup(self.s.close)

    def shared(self, run):
        a, b = self.s.intent("60", "A", "build"), self.s.intent("60", "B", "build")
        self.s.fired(a, run)
        self.s.fired(b, run)
        self.s.close_run(run, "done")

    def test_a_shared_run_is_written_once_with_one_failure_row(self):
        self.shared("r1")
        bad = {"kind": "k", "job": "60", "station": "build", "coworker": "C", "model": None, "reason": "x"}
        self.assertEqual(self.s.tools_seen("r1", "ok", {"shell": 3, "read": 1, "sleep": 1}, bad), 2)
        self.assertEqual(len(self.s.failures()), 1)
        self.assertEqual(self.s.tools_seen("r1", "ok", {"shell": 3, "read": 1, "sleep": 1}, bad), 0)
        self.assertEqual(len(self.s.failures()), 1)

    def test_a_failed_write_leaves_the_run_unread(self):
        self.shared("r2")
        with self.assertRaises(KeyError):
            self.s.tools_seen("r2", "ok", {"shell": 1, "read": 0, "sleep": 1}, {"job": "60"})
        self.assertEqual([r[0] for r in self.s.db.execute("SELECT tools_read FROM fires WHERE run_id='r2'")], [None, None])


if __name__ == "__main__":
    unittest.main()
