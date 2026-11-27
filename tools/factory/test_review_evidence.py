import contextlib, hashlib, io, json, os, re, subprocess, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof
import gate
import test_dispatch as T

BODY = "\n".join([
    "PLAN READY (facts read on dev 1615836)",
    "**Depends on**: none",
    "**Worker**: coder",
    "**Files**",
    "- `a/b.py`",
    "- `a/test_b.py`",
    "**Test file**: `a/test_b.py`",
    "**Change**",
    "- first ask",
    "- second ask",
    "- third ask",
    "**Done-test**",
    "- t",
    "**Run**",
    "```",
    "cd a && run1",
    "```",
])


def evidence(n, text="shown"):
    return "\n".join("EVIDENCE %d: %s" % (k, text) for k in range(1, n + 1))


class Reader(unittest.TestCase):
    def test_the_ask_bullets_of_the_change_are_counted_by_the_proof_reader(self):
        self.assertEqual(proof.change_asks(BODY), ["first ask", "second ask", "third ask"])
        self.assertEqual(proof.change_asks(T.ready()), [])

    def test_the_change_asks_include_corrections_and_skip_fences(self):
        body = "\n".join(["**Change**", "- one", "```", "- not an ask", "```", "**Corrections**", "- two", "**Done-test**", "- t"])
        self.assertEqual(proof.change_asks(body), ["one", "two"])

    def test_evidence_counts_each_distinct_ask_number_once(self):
        out = "EVIDENCE 1: a\nEVIDENCE 1: again\nEVIDENCE 3: c\nnoise\nEVIDENCE 4: beyond the count"
        self.assertEqual(proof.evidence(out, 3), 2)


class Review(T.Base):
    def setUp(self):
        super().setUp()
        self.w.issues[0]["body"] = BODY

    def reasons(self):
        return [r[0] for r in self.w.rows("SELECT reason FROM transitions WHERE job=5 ORDER BY id")]

    def kinds(self):
        return [r[0] for r in self.w.rows("SELECT kind FROM failures WHERE job='5'")]

    def review_message(self):
        return [m for a, m, _ in self.w.sends if "One review" in m][-1]

    def test_1691_counts_only_the_note_adopted_by_this_review_attempt(self):
        head = "6506e7dc98d7d73039375e09c73e59da84e97580"
        repo = "special-place-ai-heaven/moldwright"
        accept = "VERDICT: ACCEPT @6506e7d"
        url = "https://github.com/%s/pull/42#issuecomment-91" % repo
        endpoint = "repos/%s/issues/comments/91" % repo
        for variant in ("adopted", "bare", "wrong repo", "wrong ref PR", "wrong ref head", "malformed", "ambiguous",
                        "wrong note PR", "wrong actor", "wrong app", "wrong reviewer", "wrong attempt", "edited", "mutated", "stale", "moved head",
                        "missing comment", "partial and inline", "reject", "no verdict", "quoted", "second reviewer reuse"):
            with self.subTest(variant=variant), mock.patch.object(T, "HEAD", head):
                case = Review()
                case.setUp()
                try:
                    case.cfg["repo"] = repo
                    case.w.issues[0]["body"] = BODY.replace("- first ask\n- second ask\n- third ask", "\n".join("- ask %d" % n for n in range(1, 24)))
                    if variant == "second reviewer reuse":
                        case.w.issues[0]["body"] = case.w.issues[0]["body"].replace("a/b.py", "tools/factory/dispatch.py")
                    gh, calls, note = case.w.gh, [], {}

                    def fake_gh(args):
                        if args[:2] == ["api", endpoint]:
                            calls.append(args)
                            if variant == "missing comment":
                                raise T.D.Error("HTTP 404")
                            return json.dumps(note)
                        return gh(args)

                    case.w.gh = fake_gh
                    case.to_review()
                    keys = re.findall(r"Review-attempt: ([0-9a-f]{32})", case.review_message())
                    key = keys[0] if keys else "0" * 32
                    stamp = T.iso(case.w.clock)
                    text = "synthetic #1691\n" + evidence(22 if variant == "partial and inline" else 23)
                    body = "Review ACCEPT @6506e7dc: R1 ACCEPT @6506e7dc: %s\nReview-attempt: %s %s" % (
                        text, "f" * 32 if variant == "wrong attempt" else key, head)
                    if variant == "wrong reviewer":
                        body = body.replace("R1 ACCEPT", "R2 ACCEPT")
                    note.update(id=91, html_url=url, issue_url="https://api.github.com/repos/%s/issues/42" % repo,
                                body=body, user={"id": 358443129, "login": "moldwright-factory[bot]"},
                                performed_via_github_app={"id": 5822204}, created_at=stamp, updated_at=stamp)
                    ref = "ADOPT REVIEW NOTE: %s#42 %s 91 %s" % (repo, head, hashlib.sha256(body.encode()).hexdigest())
                    if variant == "adopted":
                        sink = io.StringIO()
                        cli = [repo, "42", "ACCEPT", "--as", "R1", "--note", text, "--attempt", key, "--sha"]
                        with mock.patch.object(gate, "gh_json", return_value={"head": {"sha": head}}), \
                                mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, url + "\n", "")) as post, \
                                contextlib.redirect_stdout(sink):
                            self.assertEqual(gate.review(cli + [head[:7]]), 2)
                            post.assert_not_called()
                            self.assertEqual(gate.review(cli + [head]), 0)
                        argv = post.call_args.args[0]
                        self.assertEqual(argv[argv.index("--body") + 1], body)
                        self.assertEqual(sink.getvalue().splitlines()[-1], ref)
                    if variant == "wrong repo":
                        ref = ref.replace(repo, "other/project")
                    if variant == "wrong ref PR":
                        ref = ref.replace("#42", "#43")
                    if variant == "wrong ref head":
                        ref = ref.replace(head, head[:-1] + "1")
                    if variant == "malformed":
                        ref = ref.replace(" 91 ", " 91?per_page=5 ")
                    if variant == "ambiguous":
                        ref += "\n" + ref
                    if variant == "quoted":
                        ref = "```text\n" + ref + "\n```"
                    if variant == "wrong note PR":
                        note["issue_url"] = note["issue_url"].replace("/42", "/43")
                    if variant == "wrong actor":
                        note["user"]["id"] = 9
                    if variant == "wrong app":
                        note["performed_via_github_app"]["id"] = 9
                    if variant == "mutated":
                        note["body"] += "\nchanged"
                    if variant in ("edited", "stale"):
                        note["updated_at"] = T.iso(case.w.clock - 30)
                    if variant == "stale":
                        note["created_at"] = note["updated_at"]
                    if variant == "bare":
                        ref = "Posted all 23 lines."
                    if variant == "partial and inline":
                        ref = "EVIDENCE 23: in the answer alone\n" + ref
                    verdict = {"reject": "VERDICT: REJECT @6506e7d: no", "no verdict": "posted"}.get(variant, accept)

                    def finish(agent):
                        case.w.finish(agent, ref + "\n" + verdict)
                        case.w.runs[case.w.order[-1][0]].update(startedAt=stamp, finishedAt=stamp)

                    finish("r1")
                    if variant == "moved head":
                        T.HEAD = "a" * 40
                    case.tick()
                    if variant == "adopted":
                        self.assertEqual(case.state(), "checks", case.reasons())
                        self.assertEqual(calls, [["api", endpoint, "--method", "GET"]])
                        self.assertIn("adopted review note: 23/23 evidence lines", case.out.getvalue())
                    elif variant == "second reviewer reuse":
                        self.assertEqual(case.state(), "review_wait", case.reasons())
                        self.assertIn("second reviewer", case.reasons()[-2])
                        case.tick()
                        self.assertNotIn(key, case.review_message())
                        self.assertEqual(case.w.order[-1][1], "r2")
                        self.assertRegex(case.review_message(), r"Review-attempt: [0-9a-f]{32}")
                        finish("r2")
                        case.tick()
                        self.assertIn("accept with 0 of 23 evidence lines: asked again", case.reasons())
                    elif variant in ("reject", "no verdict"):
                        self.assertEqual(case.state(), "fix_wait" if variant == "reject" else "rejected", case.reasons())
                        self.assertEqual(calls, [])
                    else:
                        self.assertEqual(case.state(), "review_wait", case.reasons())
                        count = 22 if variant == "partial and inline" else 0
                        self.assertIn("accept with %d of 23 evidence lines: asked again" % count, case.reasons())
                        if variant == "bare":
                            self.assertEqual(calls, [])
                            case.tick()
                            finish("r1")
                            case.tick()
                            self.assertEqual(case.state(), "blocked", case.reasons())
                        if variant in ("wrong repo", "wrong ref PR", "wrong ref head", "malformed", "ambiguous", "quoted"):
                            self.assertEqual(calls, [])
                    self.assertEqual(case.w.merges, [])
                finally:
                    case.doCleanups()

    def test_the_review_brief_lists_each_ask_and_asks_one_evidence_line_for_each_above_the_verdict(self):
        self.to_review()
        msg = self.review_message()
        self.assertIn("The asks of the Change, in order:", msg)
        for n, text in enumerate(["first ask", "second ask", "third ask"], 1):
            self.assertIn("ASK %d: %s" % (n, text), msg)
        self.assertIn("EVIDENCE <n>: <what you ran or read and what it showed>", msg)
        self.assertIn("An ACCEPT with fewer EVIDENCE lines than asks is not an ACCEPT.", msg)

    def test_an_accept_with_an_evidence_line_for_every_ask_goes_to_the_checks(self):
        self.to_review()
        self.w.finish("r1", evidence(3) + "\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "checks")

    def test_an_accept_short_of_evidence_is_asked_again_once_and_counted(self):
        self.to_review()
        self.w.finish("r1", evidence(2) + "\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "review_wait")
        self.assertIn("accept with 2 of 3 evidence lines: asked again", self.reasons())
        self.assertIn("asked again", self.kinds())
        self.tick()
        self.w.finish("r1", evidence(3) + "\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "checks")

    def test_a_second_accept_short_of_evidence_is_a_failed_review(self):
        self.to_review()
        self.w.finish("r1", evidence(2) + "\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.tick()
        self.w.finish("r1", evidence(2) + "\nVERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "blocked")
        self.assertIn("blocked: review without evidence twice: accept with 2 of 3 evidence lines", self.reasons())
        self.assertIn("review without evidence", self.kinds())
        self.assertEqual(self.w.merges, [])

    def test_a_reject_needs_only_its_sentence(self):
        self.to_review()
        self.w.finish("r1", "VERDICT: REJECT @abcdef1: the test is wrong")
        self.tick()
        self.assertEqual(self.state(), "fix_wait")

    def test_a_job_with_no_change_bullets_needs_no_evidence(self):
        self.w.issues[0]["body"] = T.ready()
        self.to_review()
        self.assertNotIn("The asks of the Change", self.review_message())
        self.w.finish("r1", "VERDICT: ACCEPT @abcdef1")
        self.tick()
        self.assertEqual(self.state(), "checks")


if __name__ == "__main__":
    unittest.main()
