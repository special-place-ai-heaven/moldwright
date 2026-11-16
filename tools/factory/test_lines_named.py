import contextlib
import unittest
import unittest.mock

import digest
import lines as L
from test_dispatch import Base


class Named(Base):
    def new(self):
        return L.Lines(self.cfg, self.w.account, self.w.gh, now=lambda: self.w.clock)

    def test_every_comment_of_a_line_ends_with_its_project(self):
        seen = []
        gh = L.named(lambda a: seen.append(a) or "", "p/q")
        gh(["issue", "comment", "5", "-R", "p/q", "--body", "stopped"])
        gh(["pr", "comment", "9", "-R", "p/q", "--body", "hello"])
        gh(["issue", "close", "5", "-R", "p/q", "--comment", "closed"])
        self.assertEqual([a[-1] for a in seen], ["stopped\n\nProject: p/q", "hello\n\nProject: p/q", "closed\n\nProject: p/q"])

    def test_what_is_not_a_comment_is_passed_on_untouched(self):
        seen = []
        gh = L.named(lambda a: seen.append(a) or "", "p/q")
        calls = [["issue", "create", "-R", "p/q", "--title", "t", "--body", "b"], ["issue", "edit", "5", "-R", "p/q", "--body", "b"],
                 ["api", "-X", "POST", "repos/p/q/issues/5/comments", "-f", "body=x"], ["issue", "close", "5", "-R", "p/q"],
                 ["issue", "comment", "5", "-R", "p/q", "--body"]]
        for a in calls:
            gh(a)
        self.assertEqual(seen, calls)

    def test_a_job_that_ends_at_home_is_told_on_its_issue_with_the_project(self):
        self.tick()
        self.w.finish("b1", "tried\nBLOCKED: the issue names no file")
        self.tick()
        said = self.w.issue(5)["comments"][-1]
        self.assertIn("BLOCKED: the issue names no file", said)
        self.assertTrue(said.endswith("\n\nProject: o/r"))

    def test_the_digest_names_the_project_and_is_posted_at_home(self):
        self.cfg.update(repo="p/q", home="o/r")
        self.w.report_answer = {"kept": True}
        posted = []
        with unittest.mock.patch.object(digest, "post", lambda gh, store, repo, d, now: posted.append((repo, d))):
            self.d = self.new().lines["p/q"]
            with contextlib.redirect_stdout(self.out):
                self.d.once()
        self.assertEqual([(repo, d["project"]) for repo, d in posted], [("o/r", "p/q")])
        self.assertNotIn("project", self.w.reports[-1]["digest"])


if __name__ == "__main__":
    unittest.main()
