import copy, json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pools
import test_planning_start as T

BOSS = "39311ebf-8324-42a4-8ab4-770acd1653f2"


def one_issue():
    return [T.issue(11, "P0", "2026-11-10T00:00:00Z")]


class Rig(T.Rig):
    def __init__(self, cfg=None, jobs=0, state="queued"):
        super().__init__(cfg)
        self.backlog = one_issue()
        self.output = ""
        for i in range(jobs):
            self.store.put_job(str(1000 + i), state, {"issue": 1000 + i})

    def gh(self, args):
        if args[:2] == ["issue", "list"] and "--search" not in args:
            self.calls.append(list(args))
            return json.dumps(self.backlog)
        if args[:2] == ["issue", "edit"] and "--add-label" in args:
            label = args[args.index("--add-label") + 1]
            for i in self.backlog:
                if str(i["number"]) == args[2]:
                    i["labels"].append({"name": label})
        return super().gh(args)

    def account(self, tool, args):
        if tool == "get_run":
            return {"status": "done", "output": self.output}
        return super().account(tool, args)


def cfg_with(max_queue=None):
    cfg = copy.deepcopy(T.CFG)
    if max_queue is not None:
        cfg["planning"] = {"max_queue": max_queue}
    return cfg


class Queue(unittest.TestCase):
    def test_no_cut_when_queue_is_at_max(self):
        r = Rig(cfg_with(20), jobs=20)
        r.station.start()
        self.assertEqual(r.sends, [])
        self.assertEqual(r.listed(), [])
        r = Rig(cfg_with(20), jobs=19)
        r.station.start()
        self.assertEqual(len(r.sends), 1)

    def test_waiting_jobs_count_too(self):
        r = Rig(cfg_with(20), jobs=20, state="waiting")
        r.station.start()
        self.assertEqual(r.sends, [])

    def test_only_waiting_and_queued_count(self):
        for state in ("building", "review_wait"):
            r = Rig(cfg_with(20), jobs=20, state=state)
            r.station.start()
            self.assertEqual(len(r.sends), 1)

    def test_max_queue_defaults_to_20(self):
        r = Rig(cfg_with(), jobs=20)
        r.station.start()
        self.assertEqual(r.sends, [])
        r = Rig(cfg_with(), jobs=19)
        r.station.start()
        self.assertEqual(len(r.sends), 1)


class Blocked(unittest.TestCase):
    def run_blocked(self, text):
        r = Rig(cfg_with())
        r.station.start()
        self.assertEqual(r.numbers(), [11])
        r.output = text
        r.station.once(2)
        return r

    def test_blocked_already_built_labels_likely_fixed(self):
        r = self.run_blocked("BLOCKED: the parent is already built by #700")
        edits = [e for e in r.edits() if e[1] == "likely-fixed"]
        self.assertEqual(edits, [("11", "likely-fixed")])
        self.assertEqual(r.store.get_all("plan:11")["state"], "blocked")
        self.assertTrue(any(c[:3] == ["issue", "comment", "11"] for c in r.calls))
        r.store.set("plan:11", "state", "unsent")
        before = len(r.sends)
        r.station.start()
        self.assertEqual(len(r.sends), before)

    def test_other_blocked_reason_no_label(self):
        r = self.run_blocked("BLOCKED: the issue names no file")
        self.assertNotIn("likely-fixed", [e[1] for e in r.edits()])
        self.assertTrue(any(c[:3] == ["issue", "comment", "11"] for c in r.calls))


class Shipped(unittest.TestCase):
    def test_shipped_settings_keep_boss_first(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch.json")
        with open(path) as f:
            cfg = json.load(f)
        cfg["repo"] = "o/r"
        cfg["types"] = {k: v for k, v in cfg["types"].items() if all("id" in c for c in v["coworkers"])}
        self.assertEqual(cfg["planning"]["max_queue"], 20)
        self.assertEqual(pools.pick_copy(cfg, "planner", [])[0], BOSS)
        r = Rig(cfg)
        r.station.start()
        self.assertEqual(r.sends[0][0], BOSS)


if __name__ == "__main__":
    unittest.main()
