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

    def test_fake_engine_is_plan_ready_not_ready(self):
        self.answer_all()
        summary = self.run_farm(write_log=True, today="2026-10-11")
        self.assertEqual(summary["status"], "plan-ready")
        self.assertTrue(summary["fake_engine"])
        report = read(os.path.join(summary["out"], "report.md"))
        self.assertTrue(report.splitlines()[2].startswith("ПЛАН ГОТОВ, ВИДЕО НЕТ"))
        self.assertNotIn("ГОТОВО", report)
        self.assertEqual(journal.due("2026-10-20", self.root), [])
        self.assertIn("PASTE_VIDEO_URL", read(os.path.join(summary["out"], "announce.txt")))

    def test_ready_only_with_real_engine(self):
        self.answer_all()
        with mock.patch.dict(os.environ, {"FAKE_ENGINE_REAL": "1"}):
            summary = self.run_farm(write_log=True, today="2026-10-11")
        self.assertEqual(summary["status"], "ready")
        self.assertFalse(summary["fake_engine"])
        self.assertEqual(len(journal.due("2026-10-12", self.root)), 1)
        self.assertTrue(read(os.path.join(summary["out"], "report.md")).splitlines()[2].startswith("ГОТОВО"))

    def test_package_complete(self):
        self.answer_all()
        summary = self.run_farm()
        folder = summary["out"]
        for name in ("plan.json", "script.md", "meta.json", "titles.md", "description.txt", "pinned.txt",
                     "tiktok.txt", "captions.srt", "cover-prompt.txt", "announce.txt", "report.md", "sites.md"):
            self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
        self.assertEqual(metalint.errors(metalint.lint(load_json(os.path.join(folder, "meta.json")))), [])
        self.assertEqual(summary["announce_issues"], [])
        self.assertEqual(len(summary["checklist"]), 20)
        self.assertEqual(summary["dropped"], ["builditapp"])
        self.assertEqual(summary["reminder"], "")
        self.assertIn("заглушка", read(os.path.join(folder, "report.md")).lower())

    def test_defaults_then_reminder(self):
        summary = self.run_farm(assume_defaults=True)
        self.assertEqual(summary["status"], "plan-ready")
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
        self.assertEqual(summary["status"], "plan-ready")
        self.assertEqual(len(summary["attempts"]), 2)
        self.assertTrue(summary["attempts"][1]["passed"])
        self.assertFalse(summary["attempts"][0]["passed"])

    def test_english_with_model_script(self):
        self.answer_all()
        summary = self.run_farm(script_path=os.path.join(FIX, "script-en.json"), lang="en")
        self.assertEqual(summary["lang"], "en")
        self.assertEqual(summary["status"], "plan-ready")
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
        self.assertEqual(summary["status"], "plan-ready")
        plan = load_json(os.path.join(summary["out"], "plan.json"))
        self.assertEqual(summary["meta_issues"], [])
        self.assertEqual(summary["announce_issues"], [])
        capture = plan["scenes"][1]["source"]["actions"][0]
        self.assertEqual((capture["do"], capture["mode"]), ("capture", "realtime"))
        self.assertIn("x_sfx_dir", plan["audio"])
        best = next(s for s in plan["scenes"] if s["id"] == "chapter-2")
        self.assertIn("hit", [x["name"] for x in best["sfx"]])

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

    def test_model_script_demo_a_is_clean(self):
        self.answer_all()
        summary = self.run_farm(script_path=os.path.join(FIX, "script-4-nahodki.json"))
        self.assertEqual(summary["status"], "plan-ready")
        self.assertEqual(summary["dropped"], ["builditapp"])
        self.assertIn("builditapp", read(os.path.join(summary["out"], "announce.txt")))
        self.assertEqual(summary["script_warnings"], [])

    def test_announce_refresh(self):
        self.answer_all()
        summary = self.run_farm()
        with self.assertRaises(ValueError):
            farm.refresh_announce(summary["out"], "youtube.com/shorts/x", self.root)
        result = farm.refresh_announce(summary["out"], "https://youtube.com/shorts/abc", self.root)
        self.assertTrue(result["changed"])
        self.assertEqual([i for i in result["issues"] if i["level"] == "ERROR"], [])
        text = read(os.path.join(summary["out"], "announce.txt"))
        self.assertIn("[ВИДЕО](https://youtube.com/shorts/abc)", text)
        self.assertEqual(load_json(os.path.join(summary["out"], "summary.json"))["video_url"], "https://youtube.com/shorts/abc")

    def test_warnings_do_not_block(self):
        self.answer_all()
        links = os.path.join(self.out, "links.txt")
        with open(links, "w", encoding="utf-8") as handle:
            handle.write("https://learn-anything.xyz/ роадмапы\n")
        summary = self.run_farm(links)
        self.assertNotEqual(summary["status"], "needs-fix")

    def test_distinct_after_log(self):
        self.answer_all()
        with mock.patch.dict(os.environ, {"FAKE_ENGINE_REAL": "1"}):
            self.run_farm(write_log=True, today="2026-10-11")
        again = self.run_farm()
        self.assertIn("НЕТ", again["checklist"][19]["state"])


if __name__ == "__main__":
    unittest.main()
