import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import load_json, read, FIX, drop, temp_skill
from vshorts import farm, journal, metalint, prefs


class Farm(unittest.TestCase):
    def setUp(self):
        self.root = temp_skill()
        self.out = tempfile.mkdtemp(prefix="viora-farm-")
        self.post = os.path.join(FIX, "post-4-nahodki.txt")

    def tearDown(self):
        drop(self.root)
        shutil.rmtree(self.out, ignore_errors=True)

    def run_farm(self, source=None, **kw):
        kw.setdefault("offline", True)
        kw.setdefault("engine_override", "fake")
        return farm.run(source or self.post, self.out, root=self.root, **kw)

    def answer_all(self):
        data = prefs.load(self.root)
        for pair in ("language=ru", "platforms=youtube_shorts,tiktok", "sources=site,html", "layout=center_bottom",
                     "qr=да", "brand=viora", "voice=male"):
            key, _, value = pair.partition("=")
            prefs.set_value(data, key, value, self.root)
        prefs.save(data, self.root)

    def test_asks_once_when_prefs_empty(self):
        with self.assertRaises(farm.FarmStop) as stop:
            self.run_farm()
        self.assertEqual(stop.exception.status, "ask")
        self.assertIn("1. Язык", stop.exception.message)

    def test_farm_one_command_ready(self):
        self.answer_all()
        summary = self.run_farm(write_log=True, today="2026-10-11")
        self.assertEqual(summary["status"], "ready")
        self.assertTrue(summary["fake_engine"])
        folder = summary["out"]
        for name in ("plan.json", "script.md", "meta.json", "titles.md", "description.txt", "pinned.txt",
                     "tiktok.txt", "captions.srt", "cover-prompt.txt", "announce.txt", "report.md", "sites.md"):
            self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
        self.assertEqual(metalint.errors(metalint.lint(load_json(os.path.join(folder, "meta.json")))), [])
        self.assertEqual(summary["announce_issues"], [])
        self.assertEqual(len(summary["checklist"]), 20)
        self.assertEqual(summary["dropped"], ["builditapp"])
        self.assertEqual(summary["reminder"], "")
        report = read(os.path.join(folder, "report.md"))
        self.assertIn("ЗАГЛУШКОЙ", report)
        self.assertEqual(len(journal.due("2026-10-12", self.root)), 1)

    def test_defaults_then_reminder(self):
        summary = self.run_farm(assume_defaults=True)
        self.assertIn(summary["status"], ("ready",))
        self.assertTrue(summary["reminder"].startswith("Не заполнено:"))
        self.assertIn("своё видео для верхней панели", summary["reminder"])

    def test_without_engine_plan_ready(self):
        self.answer_all()
        summary = self.run_farm(engine_override=None)
        self.assertEqual(summary["status"], "plan-ready")
        self.assertIn("нет рендера", summary["checklist"][0]["state"])

    def test_gate_retries_duration(self):
        self.answer_all()
        with mock.patch.dict(os.environ, {"FAKE_ENGINE_FAIL": "duration"}):
            summary = self.run_farm()
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(len(summary["attempts"]), 2)
        self.assertFalse(summary["attempts"][0]["passed"])

    def test_english_with_model_script(self):
        self.answer_all()
        summary = self.run_farm(script_path=os.path.join(FIX, "script-en.json"), lang="en")
        self.assertEqual(summary["lang"], "en")
        self.assertEqual(summary["status"], "ready")
        pkg = load_json(os.path.join(summary["out"], "meta.json"))
        self.assertEqual(metalint.errors(metalint.lint(pkg)), [])
        self.assertTrue(summary["out"].endswith("-en"))
        announce = read(os.path.join(summary["out"], "announce.txt"))
        self.assertIn("#шортс", announce)

    def test_html_fixture(self):
        self.answer_all()
        summary = self.run_farm(os.path.join(FIX, "mini-film.html"), script_path=os.path.join(FIX, "script-html.json"),
                                speed_spec="0-4:1.5,4-8:0.6,8-12:2", sound="page")
        self.assertEqual(summary["kind"], "html")
        self.assertEqual(summary["status"], "ready")
        plan = load_json(os.path.join(summary["out"], "plan.json"))
        capture = plan["scenes"][1]["source"]["actions"][0]
        self.assertEqual((capture["do"], capture["mode"]), ("capture", "realtime"))

    def test_bad_script_stops(self):
        self.answer_all()
        bad = os.path.join(self.out, "bad.json")
        data = load_json(os.path.join(FIX, "script-en.json"))
        data["beats"][0]["say"] = "Hello guys, in this video three sites."
        json.dump(data, open(bad, "w"))
        with self.assertRaises(farm.FarmStop) as stop:
            self.run_farm(script_path=bad)
        self.assertEqual(stop.exception.status, "script")

    def test_all_sites_blocked(self):
        self.answer_all()
        with self.assertRaises(farm.FarmStop) as stop:
            self.run_farm("builditapp.\n- Майнкрафт.\n\n#сервисы\n")
        self.assertEqual(stop.exception.status, "no-sites")

    def test_distinct_after_log(self):
        self.answer_all()
        self.run_farm(write_log=True, today="2026-10-11")
        again = self.run_farm()
        self.assertIn("НЕТ", again["checklist"][19]["state"])


if __name__ == "__main__":
    unittest.main()
