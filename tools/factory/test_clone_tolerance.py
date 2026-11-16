import os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

import test_factory as T

F = T.F
HERE = os.path.dirname(os.path.abspath(__file__))
CLONE_MSG = "a job clone, not a worktree of the shared clone"


class CloneCase(T.FactoryCase):
    def setUp(self):
        super().setUp()
        self.prs = {}

    def sweep(self, *argv):
        with mock.patch.object(F, "pr_lookup", lambda full, branch: self.prs.get(branch, [])):
            return self.call(F.cmd_wt, ["sweep"] + list(argv))

    def verdicts(self, out):
        return {l.split()[1]: l.split()[0] for l in out.splitlines() if l.split()[:1] in (["KEEP"], ["REMOVE"], ["RESCUE"])}

    def job_clone(self, issue="8", chunk="1"):
        path = os.path.join(F.WT, T.REPO, "%s-%s" % (issue, chunk))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        T.git(self.tmp, "clone", "--quiet", self.origin, path)
        for k, v in (("user.name", "t"), ("user.email", "t@localhost"), ("commit.gpgsign", "false")):
            T.git(path, "config", k, v)
        T.git(path, "checkout", "--quiet", "-b", "chunk/%s-%s" % (issue, chunk))
        self.commit(path, "only-in-clone.txt", "x\n")
        return path


class CloneTolerance(CloneCase):
    def test_sweep_keeps_a_clone_whose_commit_the_shared_clone_lacks(self):
        path = self.job_clone()
        code, out = self.sweep()
        self.assertEqual(code, 0, out)
        self.assertIn("KEEP   rerun/8-1  " + CLONE_MSG, out.splitlines())
        code, out = self.sweep("--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(path))

    def test_sweep_still_reads_a_worktree_beside_a_clone(self):
        self.job_clone()
        self.wt(chunk="1")
        code, out = self.sweep()
        self.assertEqual(code, 0, out)
        self.assertIn("rerun/7-1", self.verdicts(out))
        self.assertIn("rerun/8-1", self.verdicts(out))
        self.assertNotIn(CLONE_MSG, [l for l in out.splitlines() if "rerun/7-1" in l][0])

    def test_wt_done_on_a_clone_refuses_and_deletes_nothing(self):
        path = self.job_clone()
        head = T.git(path, "rev-parse", "HEAD")
        code, out = self.call(F.cmd_wt, ["done", T.REPO, "8", "1"])
        self.assertEqual(code, 2, out)
        self.assertIn("REFUSED: ", out)
        self.assertIn("is a job clone", out)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(T.git(path, "rev-parse", "HEAD"), head)

    def test_a_contains_error_means_unprovable(self):
        path = self.job_clone()
        with mock.patch.object(F, "SWEEP_FETCH", {self.clone: True}):
            self.assertIsNone(F.unsaved(self.clone, path, "chunk/8-1"))

    def test_the_marker_is_set(self):
        self.assertEqual(F.CLONE_SAFE, 1)


class InstallMarker(unittest.TestCase):
    def install(self, strip):
        tmp = tempfile.mkdtemp(prefix="clone-tol-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = os.path.join(tmp, "tree")
        shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("__pycache__"))
        if strip:
            fp = os.path.join(tree, "factory.py")
            with open(fp) as f:
                lines = [l for l in f.read().split("\n") if l != "CLONE_SAFE = 1"]
            with open(fp, "w") as f:
                f.write("\n".join(lines))
        prefix = os.path.join(tmp, "prefix")
        r = subprocess.run(["sh", os.path.join(tree, "install.sh"), "--prefix", prefix, "--jev-keyfile", "/nonexistent"], capture_output=True, text=True)
        return r, prefix

    def test_a_tree_without_the_marker_is_refused_and_nothing_is_written(self):
        r, prefix = self.install(True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("REFUSED", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(prefix))

    def test_a_tree_with_the_marker_installs(self):
        r, prefix = self.install(False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(prefix, "factory", "factory.py")))


if __name__ == "__main__":
    unittest.main()
