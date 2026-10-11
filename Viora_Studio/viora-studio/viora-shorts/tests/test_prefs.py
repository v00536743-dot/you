import os
import unittest
from unittest import mock

from helpers import drop, temp_skill
from vshorts import prefs


class Prefs(unittest.TestCase):
    def setUp(self):
        self.root = temp_skill()

    def tearDown(self):
        drop(self.root)

    def test_links_from_brand_not_invented(self):
        data = prefs.load(self.root)
        self.assertEqual(data["links"]["telegram"], "https://t.me/VioraStudio")
        self.assertEqual(data["links"]["youtube"], "https://www.youtube.com/@badVIno-VS")
        self.assertEqual(data["links"]["handle"], "BADVINO")

    def test_questions_in_one_message(self):
        text = prefs.questions_message(prefs.load(self.root))
        lines = text.splitlines()
        self.assertEqual(len(lines), 1 + len(prefs.QUESTIONS))
        self.assertTrue(lines[1].startswith("1. Язык"))
        self.assertIn("одним сообщением", lines[0])
        self.assertNotIn("генератор", text.lower())

    def test_set_and_remember(self):
        data = prefs.load(self.root)
        prefs.set_value(data, "language", "английский", self.root)
        prefs.set_value(data, "platforms", "шортс, тикток", self.root)
        prefs.set_value(data, "layout", "center_only", self.root)
        prefs.set_value(data, "qr", "да", self.root)
        prefs.set_value(data, "brand", "mono", self.root)
        prefs.set_value(data, "voice", "женский", self.root)
        prefs.set_value(data, "sources", "site,html", self.root)
        prefs.save(data, self.root)
        again = prefs.load(self.root)
        self.assertEqual(prefs.missing(again), [])
        eff = prefs.effective(again)
        self.assertEqual(eff["language"], "en")
        self.assertEqual(eff["platforms"], ["youtube_shorts", "tiktok"])
        self.assertEqual(eff["voice"]["voice"], "en-US-AvaMultilingualNeural")
        self.assertEqual(eff["brand"]["preset"], "mono")

    def test_bad_values(self):
        data = prefs.load(self.root)
        for key, value in (("layout", "two"), ("platforms", "vk"), ("brand", "neon"), ("qr", "может"),
                           ("voice.speed", "3"), ("links.telegram", "t.me/x"), ("nope", "1")):
            with self.assertRaises(ValueError, msg=key):
                prefs.set_value(data, key, value, self.root)

    def test_skip_pending_reminder(self):
        data = prefs.load(self.root)
        prefs.set_value(data, "language", "ru", self.root)
        skipped = prefs.skip(data)
        self.assertNotIn("language", skipped)
        self.assertIn("layout", data["pending"])
        self.assertEqual(prefs.missing(data), [])
        line = prefs.reminder(data)
        self.assertTrue(line.startswith("Не заполнено: "))
        self.assertTrue(line.endswith("Дать сейчас?"))
        self.assertEqual(line.count("\n"), 0)
        prefs.set_value(data, "layout", "three", self.root)
        self.assertNotIn("layout", data["pending"])

    def test_reset(self):
        data = prefs.load(self.root)
        prefs.set_value(data, "language", "en", self.root)
        prefs.save(data, self.root)
        prefs.reset(self.root)
        self.assertIsNone(prefs.load(self.root)["language"])

    def test_language_switch_resets_voice(self):
        data = prefs.load(self.root)
        prefs.set_value(data, "voice", "ru-RU-SvetlanaNeural", self.root)
        self.assertTrue(prefs.effective(data, "en")["voice"]["voice"].startswith("en-"))
        self.assertEqual(prefs.effective(data)["voice"]["voice"], "ru-RU-SvetlanaNeural")

    def test_titles_memory(self):
        data = prefs.load(self.root)
        prefs.remember_title(data, "A")
        prefs.remember_title(data, "B", chosen=False)
        self.assertEqual(data["title_style"], {"chosen": ["A"], "rejected": ["B"]})

    def test_image_generator_presence_only(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            found = prefs.image_generator()
        self.assertTrue(found["available"])
        self.assertEqual(found["keys"], ["OPENAI_API_KEY"])
        self.assertNotIn("sk-test", str(found))


if __name__ == "__main__":
    unittest.main()
