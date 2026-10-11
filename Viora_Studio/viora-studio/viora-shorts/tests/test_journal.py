import os
import unittest

from helpers import load_json, read, drop, temp_skill
from vshorts import journal


class Journal(unittest.TestCase):
    def setUp(self):
        self.root = temp_skill()

    def tearDown(self):
        drop(self.root)

    def test_measurement_cycle(self):
        out = journal.add("three-finds", "3 НАХОДКИ 😱 #shorts #a #b", ["youtube_shorts"], 27, "2026-10-11", self.root)
        self.assertEqual((out["h24"], out["d7"]), ("2026-10-12", "2026-10-18"))
        self.assertEqual(journal.due("2026-10-11", self.root), [])
        due = journal.due("2026-10-12", self.root)
        self.assertEqual([(d["name"], d["window"]) for d in due], [("three-finds", "24h")])
        row = journal.measure("three-finds", "24h", {"shown": 1200, "viewed_pct": 71, "avg_pct": 64,
                                                      "likes": 30, "subs": 4, "clicks": 9}, "2026-10-12", self.root)
        self.assertIn("| 1200 | 71 | 64 | 30 | 4 | 9 |", row)
        metrics = read(os.path.join(self.root, "memory", "metrics.md"))
        self.assertIn(journal.SECTION, metrics)
        self.assertIn("## Время публикации", metrics)
        self.assertEqual(journal.due("2026-10-13", self.root), [])
        self.assertEqual(len(journal.due("2026-10-20", self.root)), 1)

    def test_no_duplicates(self):
        journal.add("x", "t", ["tiktok"], 30, "2026-10-11", self.root)
        self.assertIn("уже", journal.add("x", "t", ["tiktok"], 30, "2026-10-11", self.root)["note"])

    def test_unknown_reel(self):
        with self.assertRaises(ValueError):
            journal.measure("nope", "24h", {}, root=self.root)

    def test_suggest_one_change(self):
        self.assertIn("первый кадр", journal.suggest({"viewed_pct": 40}))
        self.assertIn("середину", journal.suggest({"viewed_pct": 80, "avg_pct": 40}))
        self.assertIn("призыв", journal.suggest({"viewed_pct": 80, "avg_pct": 80, "subs": 0}))
        self.assertIn("название", journal.suggest({"shown": 100}, {"shown": 1000}))

    def test_experiment(self):
        row = journal.add_experiment("первый кадр", "результат в кадре", "x", "2026-10-11", self.root)
        self.assertIn("ждём замер", row)
        self.assertTrue(os.path.exists(os.path.join(self.root, "memory", "experiments.md")))


if __name__ == "__main__":
    unittest.main()
