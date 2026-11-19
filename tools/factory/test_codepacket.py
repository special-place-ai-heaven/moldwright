import contextlib, io, os, subprocess, sys, tempfile, types, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codepacket as C
import factory as F

FILES = "**Files**\n- `tools/factory/small.py`\n- `tools/factory/big.py`\n- `tools/factory/test_new.py`\n\n**Change**\n- `big.py`: `wanted` returns 2.\n\n"
BODY = FILES + ("filler text " * 420)[:5000] + "\nEND-OF-BODY"
SMALL = "def a():\n    return 1\n"
BIG = "def other():\n" + "    x = 1\n" * 2000 + "\n\ndef wanted():\n    return 2\n"
TS = """export class A {
    constructor(a) {
        this.a = a
    }
    async run(x: string): Promise<void> {
        if (x) {
            this.a = 1
        } else {
            this.a = 2
        }
        for (const y of [1]) {
            this.a += y
        }
        switch (x) {
            case 'a':
                break
        }
        while (false) {
        }
        try {
            describe("x", function () {
            })
        } catch (e) {
        }
    }
}
"""


def issue(n, body, pr=False):
    it = {"title": "T", "state": "open", "labels": [], "user": {"login": "u"}, "updated_at": "2026-11-19T00:00:00Z",
          "html_url": "https://x/%d" % n, "body": body}
    if pr:
        it["pull_request"] = {}
    return it


def comment(body, at="2026-11-19T01:00:00Z"):
    return {"user": {"login": "u"}, "created_at": at, "body": body}


class Packet(unittest.TestCase):
    def packet(self, routes, reads, ref=("dev", "abc123456789"), diff="", seen=None):
        out = io.StringIO()

        def api(path, *a, **k):
            for key, value in routes.items():
                if path.split("?")[0].endswith(key):
                    return value
            return None

        def read_at(full, path, sha, timeout):
            if seen is not None and not seen:
                seen.append(out.getvalue())
            return reads.get(path)
        with mock.patch.object(F, "api", api), mock.patch.object(F, "code_ref", lambda full, left: ref), \
                mock.patch.object(F, "read_at", read_at), \
                mock.patch.object(F, "run", lambda *a, **k: types.SimpleNamespace(stdout=diff, stderr="", returncode=0)), \
                contextlib.redirect_stdout(out):
            F.cmd_packet(["moldwright", str(routes["_n"])])
        return out.getvalue()

    def test_an_issue_shows_its_whole_text_then_the_code_of_its_files(self):
        seen = []
        got = self.packet({"_n": 7, "issues/7": issue(7, BODY), "issues/7/timeline": [], "issues/7/comments": []},
                          {"tools/factory/small.py": SMALL, "tools/factory/big.py": BIG}, seen=seen)
        for part in ("END-OF-BODY", "## Code on dev @ abc12345", "def a():\n    return 1", "1: def other():", "def wanted():\n    return 2",
                     "`tools/factory/test_new.py`: not on dev @ abc12345"):
            self.assertIn(part, got)
        self.assertNotIn("    x = 1", got)
        self.assertIn("END-OF-BODY", seen[0])

    def test_an_issue_packet_stays_inside_the_budget(self):
        body = "**Files**\n- `a.py`\n- `b.py`\n- `c.py`\n\n" + "b" * 9000 + "\U0001F600" * 2000
        got = self.packet({"_n": 7, "issues/7": issue(7, body), "issues/7/timeline": [],
                           "issues/7/comments": [comment("c" * 700) for _ in range(5)]},
                          {p: "x = 1\n" * 1980 for p in ("a.py", "b.py", "c.py")})
        self.assertLessEqual(C.units(got), 40001)
        self.assertTrue(any(line.startswith("### `c.py`") for line in got.splitlines()))

    def pr_routes(self):
        pr = {"base": {"ref": "dev"}, "head": {"ref": "chunk/8-a2", "sha": "0123456789abcdef"}, "draft": False, "merged": False,
              "mergeable_state": "clean", "additions": 1, "deletions": 0, "changed_files": 1}
        return {"_n": 8, "issues/8": issue(8, "PR body", pr=True), "pulls/8": pr, "check-runs": {"check_runs": []}, "pulls/8/files": [],
                "issues/8/comments": [comment("LAST-COMMENT", "2026-11-19T02:00:00Z")],
                "pulls/8/reviews": [{"user": {"login": "r"}, "submitted_at": "2026-11-19T01:00:00Z", "state": "CHANGES_REQUESTED",
                                     "body": "fix the cap"}]}

    def test_a_long_diff_leaves_room_for_the_reviews(self):
        got = self.packet(self.pr_routes(), {}, diff="\n".join("d" * 300 for _ in range(400)))
        for part in ("[review CHANGES_REQUESTED] fix the cap", "LAST-COMMENT", "[... diff cut at the packet's 40000 characters"):
            self.assertIn(part, got)
        self.assertLessEqual(C.units(got), 40001)

    def test_a_pr_names_its_worktree(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(F, "WT", tmp):
            os.makedirs(os.path.join(tmp, "rerun", "8-a2"))
            self.assertIn("worktree: %s" % os.path.join(tmp, "rerun", "8-a2"), self.packet(self.pr_routes(), {}))
            os.rmdir(os.path.join(tmp, "rerun", "8-a2"))
            self.assertIn("worktree: none on this server for chunk/8-a2", self.packet(self.pr_routes(), {}))

    def test_unreadable_files_still_leave_the_text_and_the_header(self):
        got = self.packet({"_n": 7, "issues/7": issue(7, BODY), "issues/7/timeline": [], "issues/7/comments": []}, {})
        self.assertIn("END-OF-BODY", got)
        self.assertIn("## Code on dev", got)


class Section(unittest.TestCase):
    def test_the_reads_stop_at_the_deadline(self):
        clock, timeouts = [0.0], []

        def read(path, timeout):
            timeouts.append(timeout)
            clock[0] += 6
            return "x = 1\n"
        body = "**Files**\n- `a.py`\n- `b.py`\n- `c.py`\n- `d.py`\n"
        got = C.section(body, 9, read, "dev @ abc", 40000, 15, clock=lambda: clock[0])
        self.assertEqual(timeouts, [6, 6, 3])
        self.assertIn("`d.py`: not shown, the packet's 15 s for code reads ran out", got)

    def test_a_small_room_turns_a_file_into_an_outline_then_into_a_line(self):
        b = "".join("def f%d():\n" % k + "".join("    x = %d\n" % j for j in range(6)) + "    return x\n" for k in range(100))
        body = "**Files**\n- `a.py`\n- `b.py`\n"
        reads = {"a.py": SMALL, "b.py": b}
        wide = C.section(body, 9, lambda p, t: reads[p], "dev @ abc", 5000, 15)
        self.assertIn("### `b.py` (800 lines: outline and the named definitions)", wide)
        self.assertNotIn("x = 2", wide)
        narrow = C.section(body, 9, lambda p, t: reads[p], "dev @ abc", 1000, 15)
        self.assertIn("`b.py`: not shown, the packet's code room of 1000 characters is used", narrow)
        self.assertIn("def a():\n    return 1", narrow)


class Units(unittest.TestCase):
    def test_python_definitions(self):
        self.assertEqual(C.python_defs("def f(\n    a,\n):\n    return a\n\n\ndef g():\n    pass\n"), [(1, 4, "f", 0, 1), (7, 8, "g", 0, 7)])

    def test_named_blocks_in_typescript(self):
        lines = TS.splitlines()
        self.assertEqual(len(lines), 26)
        self.assertEqual(C.named(lines, "run"), [(5, 25)])
        self.assertEqual(C.named(lines, "A"), [(1, 26)])
        self.assertEqual(C.named(lines, "describe"), [])

    def test_a_long_definition_is_cut_with_its_sed_line(self):
        text = "def wanted():\n" + "    x = '%s'\n" % ("a" * 80) * 199
        got = C.render("w.py", text, ["wanted"], "dev @ abc")
        self.assertIn("lines 1-200:", got)
        self.assertIn("[... 50 more lines: sed -n '151,200p' w.py]", got)
        self.assertEqual(got.count("    x = '"), 149)

    def test_the_ref_falls_back_from_dev_to_the_default_branch(self):
        answers = {"repos/o/r/branches/dev": None, "repos/o/r": {"default_branch": "main"}, "repos/o/r/branches/main": {"commit": {"sha": "m1"}}}
        with mock.patch.object(F, "gh_json", lambda path, timeout: answers[path]):
            self.assertEqual(F.code_ref("o/r", lambda: 15), ("main", "m1"))

    def test_a_read_that_times_out_gives_none(self):
        def slow(*a, **k):
            raise subprocess.TimeoutExpired("gh", 6)
        with mock.patch.object(F.subprocess, "run", slow):
            self.assertIsNone(F.read_at("o/r", "a.py", "abc", 6))


if __name__ == "__main__":
    unittest.main()
