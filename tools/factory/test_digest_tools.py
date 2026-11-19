import datetime, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest
import limits as L
import store as S

SINCE = "2026-11-19T10:00:00Z"
ZERO = {"runs": 0, "measured": 0, "unread": 0, "shellPerRun": None, "readShare": None, "sleepRuns": 0}


def at(offset):
    return datetime.datetime.fromtimestamp(L.ts(SINCE) + offset, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ToolUse(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.s = S.Store(os.path.join(d.name, "l.db"))
        self.addCleanup(self.s.close)
        self.now = L.ts(SINCE) + 7200

    def run_of(self, run, stage, sent, ended, how, counts=None, fires=1):
        for k in range(fires):
            self.s.fired(self.s.intent("5", "c%d" % k, stage, at=at(sent)), run)
        self.s.close_run(run, "done", at=at(ended))
        self.s.tools_seen(run, how, None if counts is None else dict(zip(("shell", "read", "sleep"), counts)))

    def test_runs_on_both_sides_of_the_start(self):
        self.s.set("-", "tools_since", SINCE)
        self.run_of("r1", "build", -3600, -1800, "ok", (10, 4, 1))
        self.run_of("r2", "build", 60, 600, "ok", (10, 4, 1))
        self.run_of("r3", "fix of #3", 60, 700, "ok", (6, 2, 0))
        self.run_of("r4", "build", 60, 800, "refused")
        self.run_of("r5", "build", 60, 900, "ok", (4, 4, 0), fires=2)
        self.run_of("r6", "review 1 of #3 at abc", 60, 900, "ok", (50, 50, 5))
        self.run_of("r7", "build", -200000, -100000, "ok", (9, 9, 9))
        self.run_of("r8", "build", -60, 60, "ok", (7, 7, 7))
        got = digest.tool_use(self.s, self.now)
        self.assertEqual(got["since"], SINCE)
        self.assertEqual(got["before"], {"runs": 1, "measured": 1, "unread": 0, "shellPerRun": 10.0, "readShare": 0.4, "sleepRuns": 1})
        self.assertEqual(got["day"], {"runs": 4, "measured": 3, "unread": 1, "shellPerRun": 6.67, "readShare": 0.5, "sleepRuns": 1})

    def test_an_empty_store(self):
        self.assertEqual(digest.tool_use(self.s, self.now), {"since": None, "before": ZERO, "day": ZERO})

    def test_the_digest_carries_it(self):
        self.s.set("-", "tools_since", SINCE)
        self.run_of("r2", "build", 60, 600, "ok", (10, 4, 1))
        got = digest.build(self.s, {}, self.now)["tools"]
        self.assertEqual(got, digest.tool_use(self.s, self.now))
        json.dumps(got)


if __name__ == "__main__":
    unittest.main()
