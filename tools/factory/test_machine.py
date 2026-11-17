import json, os, re, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import machine
import problems

NOW = __import__("time").time()


def keeper(readings=None, factory=None, made="2027-01-15T08:00:00Z"):
    return {"version": 1, "madeAt": made, "engine": "running", "skippedTicks": 0,
            "readings": readings if readings is not None else [
                {"name": "load_1", "value": 4.5, "reason": None},
                {"name": "disk_free_kb", "value": None, "reason": "df failed"}],
            "housekeeping": [{"cmd": "mirror", "rc": 0, "s": 3}],
            "factory": factory if factory is not None else {"version": 1, "readings": [{"name": "wt_count", "value": 7, "reason": None}]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "machine.json")

    def write(self, doc, age=60, raw=None):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(doc))
        os.utime(self.path, (NOW - age, NOW - age))


class Read(Base):
    def test_a_fresh_file_gives_every_reading_with_its_source_and_the_file_age(self):
        self.write(keeper())
        m = machine.read(NOW, self.path)
        values = {r["name"]: (r["value"], r["reason"], r["source"]) for r in m["readings"]}
        self.assertEqual(values["load_1"], (4.5, None, "keeper"))
        self.assertEqual(values["disk_free_kb"], (None, "df failed", "keeper"))
        self.assertEqual(values["wt_count"], (7, None, "factory"))
        self.assertEqual(m["fileAgeS"], 60)
        self.assertTrue(m["fresh"])
        self.assertEqual(m["engine"], "running")
        self.assertEqual(m["fileMadeAt"], "2027-01-15T08:00:00Z")
        self.assertEqual(m["housekeeping"], [{"cmd": "mirror", "rc": 0, "s": 3}])
        self.assertIsNone(machine.silent(m))

    def test_a_file_older_than_15_minutes_shows_every_value_as_unknown_never_the_last_number(self):
        self.write(keeper(), age=901)
        m = machine.read(NOW, self.path)
        self.assertFalse(m["fresh"])
        self.assertEqual(m["engine"], "unknown")
        self.assertEqual(m["housekeeping"], [])
        self.assertTrue(m["readings"])
        for r in m["readings"]:
            self.assertIsNone(r["value"])
            self.assertEqual(r["reason"], "keeper file older than 15 minutes")
        self.assertIn("over 900 s", machine.silent(m))

    def test_missing_half_written_huge_and_not_json_never_raise(self):
        text = json.dumps(keeper())
        cases = {
            "half": (text[:40], "keeper file is not an object"),
            "huge": ("x" * (machine.MAX_BYTES + 12), "keeper file over 524288 bytes"),
            "traceback": ("Traceback (most recent call last):", "keeper file is not an object"),
            "list": ("[1, 2]", "keeper file is not an object"),
        }
        for name, (raw, reason) in cases.items():
            with self.subTest(name):
                self.write(None, raw=raw)
                m = machine.read(NOW, self.path)
                self.assertFalse(m["fresh"])
                self.assertIsNone(m["fileAgeS"])
                self.assertEqual(m["readings"], [{"name": "keeper_file", "value": None, "reason": reason, "source": "keeper"}])
                self.assertIn("keeper file", machine.silent(m))
        missing = machine.read(NOW, self.path + ".none")
        self.assertEqual(missing["readings"], [{"name": "keeper_file", "value": None, "reason": "keeper file missing", "source": "keeper"}])
        self.assertIn("no keeper file", machine.silent(missing))


class Contract(Base):
    def test_values_are_cut_to_the_contract(self):
        readings = [{"name": "n%d" % i, "value": "v" * 99, "reason": "r" * 200} for i in range(250)]
        readings += ["junk", {"value": 1}]
        housekeeping = [{"cmd": "c", "rc": 0, "s": 1} for _ in range(12)]
        self.write(keeper(readings=readings, factory={"readings": []}) | {"housekeeping": housekeeping})
        m = machine.read(NOW, self.path)
        self.assertEqual(len(m["readings"]), 200)
        self.assertEqual(len(m["housekeeping"]), 10)
        self.assertTrue(all(len(r["value"]) == 64 for r in m["readings"]))
        self.assertTrue(all(len(r["reason"]) == 120 for r in m["readings"]))

    def test_booleans_become_numbers_and_lists_become_null(self):
        self.write(keeper(readings=[{"name": "a", "value": True}, {"name": "b", "value": [1]}, {"name": "c", "value": {}}]))
        values = {r["name"]: r["value"] for r in machine.read(NOW, self.path)["readings"] if r["name"] in "abc"}
        self.assertEqual(values, {"a": 1, "b": None, "c": None})

    def test_a_full_block_holds_no_token_shape(self):
        self.write(keeper())
        text = json.dumps(machine.read(NOW, self.path))
        self.assertIsNone(re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|-----BEGIN", text))


class Alarm(Base):
    def test_a_stale_file_opens_keeper_silent_and_a_missing_one_says_so(self):
        self.write(keeper(), age=901)
        out = problems.Watch().find([], {}, set(), "", NOW, [], machine=machine.read(NOW, self.path))
        self.assertIn("over 900 s", out["keeper silent"])
        missing = problems.Watch().find([], {}, set(), "", NOW, [], machine=machine.read(NOW, self.path + ".none"))
        self.assertIn("no keeper file", missing["keeper silent"])

    def test_a_fresh_file_and_no_machine_open_nothing(self):
        self.write(keeper())
        self.assertNotIn("keeper silent", problems.Watch().find([], {}, set(), "", NOW, [], machine=machine.read(NOW, self.path)))
        self.assertNotIn("keeper silent", problems.Watch().find([], {}, set(), "", NOW, []))


class Deploy(unittest.TestCase):
    def test_the_dispatcher_mounts_the_keeper_folder_read_only_and_names_the_file(self):
        deploy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "deploy", "vps", "factory-dispatcher.yml")
        with open(deploy, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("FACTORY_KEEPER_FILE: /keeper/machine.json", text)
        self.assertIn("- /var/lib/rerun-keeper:/keeper:ro", text)
        self.assertNotIn("docker.sock", text)


if __name__ == "__main__":
    unittest.main()
