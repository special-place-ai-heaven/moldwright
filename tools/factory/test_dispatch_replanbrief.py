import unittest

import issuecheck
import proof
import redgreen


class ReplanBehavior(unittest.TestCase):
    def test_proof_asks_combines_change_and_corrections_while_redgreen_reads_only_fenced_run_lines(self):
        body = "\n".join([
            "PLAN READY (cut of #1; facts read on dev 1234567): one slice",
            "**Part of**: #1",
            "**Depends on**: none",
            "**Worker**: coder",
            "**Files**",
            "- `tools/factory/proof.py`",
            "- `tools/factory/test_dispatch_replanbrief.py`",
            "**Test file**: `tools/factory/test_dispatch_replanbrief.py`",
            "**Change**",
            "- Validate the updated ask.",
            "**Corrections**",
            "- Run `python3 -m unittest test_dispatch_replanbrief` instead.",
            "**Done-test**",
            "- `test_proof_asks_combines_change_and_corrections_while_redgreen_reads_only_fenced_run_lines`",
            "**Run**",
            "python3 -m unittest test_dispatch_replanbrief",
        ])
        tree = {"tools/factory/proof.py", "tools/factory/test_dispatch_replanbrief.py"}
        self.assertEqual(proof.change_asks(body), [
            "Validate the updated ask.",
            "Run `python3 -m unittest test_dispatch_replanbrief` instead.",
        ])
        self.assertEqual(redgreen.run_lines(body), [])
        fenced = body.replace("**Run**\npython3 -m unittest test_dispatch_replanbrief",
                              "**Run**\n```sh\ncd tools/factory && python3 -m unittest test_dispatch_replanbrief\n```")
        self.assertEqual(redgreen.run_lines(fenced), ["cd tools/factory && python3 -m unittest test_dispatch_replanbrief"])
        self.assertEqual(issuecheck.faults(fenced, tree, number=5), [])


if __name__ == "__main__":
    unittest.main()
