import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "checks.py")
SLUG_PREFIX = "runtime-check-no-such-slug."
NAMES = [
    "liveness-app",
    "liveness-engine",
    "liveness-dispatcher",
    "settings-redirect",
    "redeem-404",
    "auth-email-field",
    "published-unknown-slug",
]


class Handler(http.server.BaseHTTPRequestHandler):
    broken: str | None = None
    build_sha = "abc1234def"

    def log_message(self, *args):
        pass

    def reply(self, status, body=b"", ctype="application/json", location=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        broken = type(self).broken
        host = self.headers.get("Host", "")
        if host.startswith(SLUG_PREFIX):
            self.reply(200 if broken == "published-unknown-slug" else 404, b"gate", "text/html")
        elif self.path == "/api/version":
            if broken == "liveness-app":
                self.reply(500, b"{}")
            elif broken == "empty-sha":
                self.reply(200, b'{"buildSha":""}')
            else:
                self.reply(200, json.dumps({"buildSha": self.build_sha}).encode())
        elif self.path == "/settings":
            if broken == "settings-redirect":
                self.reply(200, b"ok", "text/html")
            else:
                self.reply(307, b"", "text/html", "/")
        elif self.path == "/redeem":
            self.reply(200 if broken == "redeem-404" else 404, b"x", "text/html")
        elif self.path == "/auth":
            if broken == "auth-email-field":
                self.reply(200, b"<html><input type='text'></html>", "text/html")
            else:
                self.reply(200, b'<html><input type="email" name="e"></html>', "text/html")
        elif self.path == "/health":
            status = "down" if broken == "liveness-engine" else "ok"
            self.reply(200, ('{"status": "%s"}' % status).encode())
        else:
            self.reply(200, b"home", "text/html")


def serve(server):
    try:
        server.serve_forever()
    except (OSError, ValueError):
        pass


def start_stub():
    for port in range(5300, 5400):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        threading.Thread(target=serve, args=(server,), daemon=True).start()
        return server
    raise RuntimeError("no free port in 5300-5399")


def free_closed_port():
    for port in range(5300, 5400):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("no free port in 5300-5399")


def run(base, *extra):
    proc = subprocess.run(
        [sys.executable, "-I", SCRIPT, base, *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = proc.stdout.splitlines()
    return proc.returncode, lines


class ChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_stub()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.server_close()

    def setUp(self):
        Handler.broken = None
        Handler.build_sha = "abc1234def"
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.beat = os.path.join(folder.name, "heartbeat")
        with open(self.beat, "w") as f:
            f.write("SECRET-BEAT-LINE")
        self.age(10)

    def age(self, seconds):
        stamp = time.time() - seconds
        os.utime(self.beat, (stamp, stamp))

    def full_args(self):
        return ["--publish-host", "example.test", "--engine-url", self.base, "--heartbeat-file", self.beat]

    def test_all_pass_liveness_lines_first(self):
        code, lines = run(self.base, *self.full_args())
        self.assertEqual(code, 0, lines)
        self.assertEqual([line.split()[1] for line in lines], NAMES)
        self.assertEqual(lines[:2], ["PASS liveness-app buildSha=abc1234", "PASS liveness-engine status=ok"])
        self.assertRegex(lines[2], r"^PASS liveness-dispatcher age=\d+s$")
        self.assertNotIn("SECRET-BEAT-LINE", "\n".join(lines))
        for line in lines:
            self.assertTrue(line.startswith("PASS "), line)

    def test_without_optional_targets_three_are_skipped_and_exit_is_zero(self):
        code, lines = run(self.base)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sum(x.startswith("PASS ") for x in lines), 4, lines)
        self.assertEqual(sum(x.startswith("SKIP ") for x in lines), 3, lines)
        self.assertIn("SKIP liveness-engine not reachable from here", lines)
        self.assertIn("SKIP liveness-dispatcher not reachable from here", lines)

    def test_empty_build_sha_fails_the_app_line(self):
        Handler.broken = "empty-sha"
        code, lines = run(self.base)
        self.assertEqual((code, lines[0]), (1, "FAIL liveness-app no buildSha"))

    def test_build_identifier_produces_one_app_line(self):
        for sha, code, first in [(" \t ", 1, "FAIL liveness-app no buildSha"),
                                 ("ab\ncd", 1, "FAIL liveness-app no buildSha"),
                                 ("rc-2", 0, "PASS liveness-app buildSha=rc-2"),
                                 ("preview.42", 0, "PASS liveness-app buildSha=preview")]:
            with self.subTest(sha=sha):
                Handler.build_sha = sha
                status, lines = run(self.base)
                self.assertEqual((status, lines[0], len(lines)), (code, first, len(NAMES)))
                self.assertEqual([line.split()[1] for line in lines], NAMES)

    def test_heartbeat_age_and_missing_file(self):
        for seconds, label in [(170, "PASS"), (180, "FAIL"), (190, "FAIL")]:
            with self.subTest(seconds=seconds):
                self.age(seconds)
                code, lines = run(self.base, *self.full_args())
                self.assertEqual(code, int(label == "FAIL"))
                self.assertRegex(lines[2], rf"^{label} liveness-dispatcher age=\d+s$")
        os.remove(self.beat)
        code, lines = run(self.base, *self.full_args())
        self.assertEqual(code, 1)
        self.assertTrue(lines[2].startswith("FAIL liveness-dispatcher "))

    def test_each_break_fails_only_its_check(self):
        for name in NAMES:
            with self.subTest(check=name):
                Handler.broken = name
                self.age(300 if name == "liveness-dispatcher" else 10)
                code, lines = run(self.base, *self.full_args())
                self.assertEqual(code, 1, lines)
                fails = [x for x in lines if x.startswith("FAIL ")]
                self.assertEqual(len(fails), 1, lines)
                self.assertEqual(fails[0].split()[1], name, lines)

    def test_nothing_listening_fails_every_check_without_hanging(self):
        port = free_closed_port()
        base = "http://127.0.0.1:%d" % port
        code, lines = run(base, "--publish-host", "example.test", "--engine-url", base, "--deadline", "2", "--heartbeat-file", self.beat + ".missing")
        self.assertEqual(code, 1, lines)
        self.assertEqual(len(lines), 7, lines)
        for line in lines:
            self.assertTrue(line.startswith("FAIL "), line)


if __name__ == "__main__":
    unittest.main()
