import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_dispatch as T


class Parked(T.Base):
    def test_a_parked_job_is_not_built_until_the_park_comes_off(self):
        self.w.issues[0]["labels"] = ["factory-paused"]
        self.tick(3)
        self.assertEqual(self.state(), "queued")
        self.assertEqual(self.w.sends, [])
        self.assertEqual(self.out.getvalue().count("parked: not built while factory-paused"), 1)
        self.w.issues[0]["labels"] = []
        self.tick()
        self.assertEqual(self.state(), "building")
        self.assertEqual(len(self.w.sends), 1)

    def test_an_unparked_job_is_built(self):
        self.tick()
        self.assertEqual(self.state(), "building")


if __name__ == "__main__":
    unittest.main()
