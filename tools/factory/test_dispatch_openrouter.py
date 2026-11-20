import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holds
import pools
import test_dispatch_renewal as R


class Pools(unittest.TestCase):
    CFG = {"types": {"coder": {"coworkers": [{"id": "c1", "name": "C1", "runs": 1},
                                             {"id": "o1", "name": "O1", "runs": 1, "provider": "openrouter"}]}}}

    def test_a_plan_hold_leaves_only_the_copies_off_the_subscription(self):
        self.assertEqual(pools.free_copies(dict(self.CFG, held_plan=True), "coder", []), [("o1", 1)])

    def test_any_other_hold_leaves_none(self):
        self.assertEqual(pools.free_copies(dict(self.CFG, held=True), "coder", []), [])

    def test_without_a_hold_every_copy_is_free(self):
        self.assertEqual(pools.free_copies(self.CFG, "coder", []), [("c1", 1), ("o1", 1)])

    def test_a_coworker_names_its_provider_and_defaults_to_the_subscription(self):
        self.assertEqual((pools.provider_of(self.CFG, "o1"), pools.provider_of(self.CFG, "c1"), pools.provider_of(self.CFG, "zz")),
                         ("openrouter", "claude", "claude"))


class Kinds(unittest.TestCase):
    def test_every_active_hold_is_seen_not_only_the_first(self):
        import tempfile
        from store import Store
        s = Store(os.path.join(tempfile.mkdtemp(), "s.db"))
        self.addCleanup(s.close)
        holds.arm(s, "plan week", 2000)
        holds.arm(s, "disk", 2000)
        holds.arm(s, "update", 500)
        self.assertEqual(holds.active_kinds(s, 1000), {"plan week", "disk"})
        self.assertEqual((holds.blocks_all(s, 1000), holds.blocks_subscription(s, 1000)), (True, True))
        holds.clear(s, "disk")
        self.assertEqual((holds.blocks_all(s, 1000), holds.blocks_subscription(s, 1000)), (False, True))


class OffTheSubscription(unittest.TestCase):
    beat, state, hold = R.PlanWeek.beat, R.PlanWeek.state, R.PlanWeek.hold
    make = R.PlanWeek.make

    def builders(self, provider):
        for b in self.d.cfg["builders"]:
            b["provider"] = provider

    def test_a_plan_week_hold_still_sends_to_a_builder_off_the_subscription_with_its_own_model(self):
        self.make(96)
        self.builders("openrouter")
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(self.hold()["kind"], "plan week")
        self.assertEqual(len(self.w.sends), 1)
        self.assertNotIn("model", self.w.send_args[-1])
        self.assertNotIn("thinkingLevel", self.w.send_args[-1])

    def test_a_plan_week_hold_still_stops_a_builder_on_the_subscription(self):
        self.make(96)
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(len(self.w.sends), 0)

    def make_many(self, used, issues):
        R.Renewal.make(self, issues)
        self.w.sign_in = {"minutesLeft": 400, "renewalDue": False}
        self.d.cfg["plan_week_hold_percent"] = 95
        self.d.cfg["slots"] = 15
        inner = self.d.account

        def account(tool, args, timeout=30):
            got = inner(tool, args)
            if tool == "list_ai_connections":
                got["connections"][0]["planLimits"] = {"windows": [{"kind": "weekly", "label": None, "usedPercent": used,
                                                                    "resetsAt": "2099-01-01T00:00:00.000Z"}]}
            return got
        self.d.account = account

    def test_the_plan_week_pacing_does_not_throttle_builders_off_the_subscription(self):
        self.make_many(98, [R.issue(5), R.issue(6)])
        self.builders("openrouter")
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(self.hold()["kind"], "plan week")
        self.assertEqual(len(self.w.sends), 2)

    def test_a_spent_quota_off_the_subscription_holds_no_subscription_coworker(self):
        self.make(10)
        self.builders("openrouter")
        self.beat()
        job = self.d.store.get_job("5")
        self.d.plan_limit_or_fail(job, "openrouter: quota exceeded", "quota exceeded")
        self.assertIsNone(holds.active(self.d.store, self.w.clock))

    def with_a_tier_model(self):
        inner = self.d.tier_job

        def tier_job(j, state):
            inner(j, state)
            j["run_model"] = {"model": "claude-opus-5-5", "thinkingLevel": "high"}
        self.d.tier_job = tier_job

    def fired_models(self):
        return {r[0] for r in self.d.store.db.execute("SELECT model FROM fires WHERE job='5'").fetchall()}

    def test_the_run_record_and_the_send_name_no_model_off_the_subscription(self):
        self.make(96)
        self.builders("openrouter")
        self.with_a_tier_model()
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(self.fired_models(), {None})
        self.assertNotIn("model", self.w.send_args[-1])

    def test_the_run_record_and_the_send_name_the_tier_model_on_the_subscription(self):
        self.make(10)
        self.with_a_tier_model()
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(self.fired_models(), {"claude-opus-5-5"})
        self.assertEqual(self.w.send_args[-1]["model"], "claude-opus-5-5")

    def test_a_disk_hold_stops_every_builder(self):
        self.make(10)
        self.builders("openrouter")
        holds.arm(self.d.store, "disk", self.w.clock + 3600)
        self.beat()
        self.w.clock += 30
        self.beat()
        self.assertEqual(len(self.w.sends), 0)


if __name__ == "__main__":
    unittest.main()
