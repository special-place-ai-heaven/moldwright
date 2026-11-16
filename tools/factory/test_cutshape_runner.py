import unittest

import cutshape
import planning

FORM = """PLAN READY (cut of #1; facts read on dev 4296d1f)

**Worker**: coder
**Test file**: `tools/factory/test_cutshape_runner.py`

**Files** (allowed paths; nothing else)
- `tools/factory/cutshape.py`
- `tools/factory/test_cutshape_runner.py`

**Change**
text

**Run**
```
%s
```

**Depends on**: none
"""


def child(run):
    return {"number": 5, "body": FORM % run}


def run_errors(run):
    return [e for e in cutshape.check([child(run)])[5] if e.startswith("run line:")]


class CutShapeRunner(unittest.TestCase):
    def test_a_uvx_run_line_is_refused(self):
        errs = run_errors("uvx ruff@0.17.5 check tools/factory")
        self.assertEqual(len(errs), 1)
        self.assertIn("run line: uvx", errs[0])

    def test_a_cd_then_uvx_run_line_is_refused(self):
        errs = run_errors("cd tools/factory && uvx ruff check .")
        self.assertEqual(len(errs), 1)
        self.assertIn("run line: uvx", errs[0])

    def test_python_run_lines_pass(self):
        run = "\n".join([
            'cd tools/factory && python3 -I -m unittest discover -s . -p "test_cutshape_runner.py" -v',
            'cd tools/factory && python3 -I -m unittest discover -s . -p "test_*.py"',
        ])
        self.assertEqual(run_errors(run), [])

    def test_the_brief_says_the_runner_has_no_uvx(self):
        text = planning.brief({"number": 1, "title": "t"}, "o/rerun")
        self.assertIn("uvx", text)
        self.assertIn("runs on the CI runner", text)
        self.assertIn("which has no `uvx`: use none", text)
        cut_line = [l for l in text.splitlines() if "cut format of #333" in l][0]
        self.assertNotIn("uvx", cut_line)


if __name__ == "__main__":
    unittest.main()
