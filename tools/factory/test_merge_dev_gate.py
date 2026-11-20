import contextlib, io, json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch as D
import factory as F
from test_dispatch import Base, HEAD, ready, wf

PR = {"base": {"ref": "dev"}, "head": {"ref": "chunk/7-1", "sha": "a" * 40}, "state": "open", "draft": False, "merge_commit_sha": "0" * 40}


class MergeDevGate(unittest.TestCase):
    def merge(self, gate_code):
        calls = []

        def fake_api(path, *a, **k):
            return [] if path.endswith("/files?per_page=100") else {"default_branch": "main"} if path.count("/") == 2 else PR

        def fake_run(cmd, *a, **k):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, gate_code if cmd[1].endswith("gate.py") else 0, "GATE", "")

        green = [{"name": "ci", "status": "completed", "conclusion": "success", "id": 1, "url": ""}]
        out = io.StringIO()
        with mock.patch.object(F, "api", fake_api), mock.patch.object(F, "run", fake_run), mock.patch.object(F, "checks", lambda *a: green), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                F.cmd_merge_dev(["rerun", "9"])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, calls

    def test_refused_without_pass_at_head(self):
        code, calls = self.merge(1)
        self.assertNotEqual(code, 0)
        self.assertFalse(any(c[1:3] == ["pr", "merge"] for c in calls))
        self.assertTrue(any(c[1].endswith("gate.py") for c in calls))

    def test_merges_when_gate_passes(self):
        code, calls = self.merge(0)
        self.assertEqual(code, 0)
        self.assertTrue(any(c[1:3] == ["pr", "merge"] for c in calls))



class DispatchMergeSafety(Base):
    builders = ["b1"]

    def setUp(self):
        super().setUp()
        self.cfg["resolver"] = {"detect": True, "resolve": False}
        self.cfg["reviewers"] = [{"id": "r1", "name": "R1"}]

    def test_holds_merge_on_same_beat_dev_turns_red_and_rejects_mismatched_merged_head(self):
        self.to_checks()
        self.w.workflows[HEAD] = [wf("ci", "success")]
        self.tick()
        self.assertEqual(self.state(5), "merged")

        self.w.issues.append({"number": 6, "title": "B", "comments": [],
                              "body": ready().replace("a/b.py", "c/d.py").replace("a/test_b.py", "c/test_d.py")})
        self.w.pr_state = "OPEN"
        self.tick()
        self.w.finish("b1", "Done.\nPR: https://github.com/o/r/pull/43")
        self.tick(2)
        self.w.finish("r1", "ok\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(6), "checks")

        self.w.workflows[self.w.merge_sha] = [wf("Factory tools", "failure", wid=2)]
        self.tick()
        self.assertEqual(self.state(6), "checks")
        self.assertEqual(len(self.w.merges), 1)

        self.w.workflows[self.w.merge_sha] = [wf("Factory tools", "success", wid=2)]
        self.tick(2)
        gh = self.w.gh
        other_head = "9999999999999999"

        def mismatch(args):
            a = list(args)
            if a[:2] == ["pr", "merge"]:
                raise D.Error("gh pr merge failed: exit 1: head mismatch")
            if a[:2] == ["pr", "view"] and a[2] == "43":
                return json.dumps({"headRefOid": other_head, "state": "MERGED", "mergeable": "UNKNOWN",
                                   "comments": [], "mergeCommit": {"oid": "deadbeef12345678"}})
            return gh(a)

        self.w.gh = mismatch
        self.tick()
        data6 = json.loads(self.w.rows("SELECT data FROM jobs WHERE job='6'")[0][0])
        self.assertEqual(self.state(6), "merged")
        self.assertFalse(data6.get("own_merge"))

    def test_gh_wrapper_refuses_coworker_merge_and_merge_dev_binary_is_gone(self):
        here = os.path.dirname(os.path.abspath(__file__))
        self.assertFalse(os.path.exists(os.path.join(here, "bin", "merge-dev")))
        if sys.platform == "win32":
            return
        wrapper = os.path.join(here, "bin", "gh")
        with tempfile.TemporaryDirectory() as d:
            key, app, real, log_path = (os.path.join(d, n) for n in ("key", "app", "gh", "log"))
            with open(key, "w", encoding="utf-8") as f:
                f.write("shared\n")
            with open(app, "w", encoding="utf-8") as f:
                f.write("app\n%d\n" % int(time.time() + 3600))
            with open(real, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho \"$*\" >> \"$LOG\"\necho ok\n")
            os.chmod(real, 0o755)
            env = dict(os.environ, FACTORY_GH_KEY=key, FACTORY_GH_APP=app, FACTORY_GH_REAL=real, LOG=log_path)
            env.pop("FACTORY_DISPATCHER", None)
            for bad in (["pr", "merge", "9"], ["api", "-X", "PUT", "repos/o/r/pulls/9/merge"]):
                p = subprocess.run(["sh", wrapper] + bad, capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 64, bad)
                self.assertFalse(os.path.exists(log_path))
            disp_env = dict(env, FACTORY_DISPATCHER="1")
            ok = subprocess.run(["sh", wrapper, "pr", "merge", "9"], capture_output=True, text=True, env=disp_env)
            self.assertEqual(ok.returncode, 0)

if __name__ == "__main__":
    unittest.main()
