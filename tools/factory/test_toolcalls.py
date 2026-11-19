import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolcalls

READS = ["sed -n '1,5p;20,30p' f", 'grep -rn "foo|bar" src', "grep -rn 'a\\|b' .", "grep -n 'def f(x)' a.py", "grep -rn '|' src",
         "grep -n '(' f", 'grep ">" f', 'grep "sleep 5" f', "git -C /x log -3", "git show HEAD:x", "ls 2>&1 | head",
         "ls >/dev/null 2>&1", "cat a; ls b", "cat a | sort | uniq -c", "for f in a b; do cat $f; done", "timeout 30 cat a",
         "nice grep -n x f"]
OTHERS = ["sed -i s/a/b/ f", "cat a > b", "echo x>f", "git commit -m x", "git status", "find . -name x -delete",
          "find . -name x -exec cat {} \\;", "cat a | python3 x", "echo 'unterminated", 'git commit -m "fix\nsleep 2 retries"',
          "cat > s.sh <<'EOF'\nsleep 1\nEOF\nbash s.sh", "cat <<EOF > f\nsleep 9\n", "cd a && python3 -I -m unittest test_b",
          "/data/tools/bin/ci-wait rerun 42", "cat a; echo x > f", "ls; printf x >> log",
          "for f in a; do cat $f; echo $f >> log; done", "timeout 60 python3 x.py", "nice -n 5 make"]
SLEEPS = ["cd x && sleep 30", "while true; do sleep 5; done", "X=1 sleep 2", "(sleep 3)", "sleep 60; /data/tools/bin/ci-wait rerun 42",
          "timeout 60 sleep 5", "nice sleep 5", "nice -n 10 sleep 5", "stdbuf -oL sleep 5", "timeout -s KILL 2m sleep 5"]


class Classify(unittest.TestCase):
    def check(self, cmds, want):
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                self.assertEqual(toolcalls.count([{"tool": "mcp__rerun__shell_exec", "input": {"command": cmd}}])["shell"], 1)
                self.assertEqual(toolcalls.classify(cmd), want)

    def test_the_46_cases_number_46(self):
        self.assertEqual(len(READS) + len(OTHERS) + len(SLEEPS), 46)

    def test_calls_that_only_read(self):
        self.check(READS, (True, False))

    def test_calls_that_change_or_run_something(self):
        self.check(OTHERS, (False, False))

    def test_calls_that_sleep(self):
        self.check(SLEEPS, (False, True))


class Count(unittest.TestCase):
    def test_a_cut_input_a_file_tool_and_a_dict_input(self):
        calls = [{"tool": "mcp__rerun__shell_exec", "input": '{"command":"cat a; ls b… [truncated] 9 more chars elided to save context'},
                 {"tool": "fs_write", "input": {"path": "x"}},
                 {"tool": "shell_exec", "input": {"command": "sleep 1"}}]
        self.assertEqual(toolcalls.count(calls), {"shell": 2, "read": 1, "sleep": 1})

    def test_only_shell_calls_have_a_command(self):
        self.assertIsNone(toolcalls.command({"tool": "mcp__rerun__fs_edit", "input": {"command": "x"}}))
        self.assertEqual(toolcalls.command({"tool": "mcp__rerun__shell_exec", "input": '{"command": 7}'}), "")
        self.assertEqual(toolcalls.command({"tool": "mcp__rerun__shell_exec", "input": "not json"}), "")

    def test_odd_items_never_raise(self):
        self.assertEqual(toolcalls.count([None, 3, "x", {"tool": None}]), {"shell": 0, "read": 0, "sleep": 0})


if __name__ == "__main__":
    unittest.main()
