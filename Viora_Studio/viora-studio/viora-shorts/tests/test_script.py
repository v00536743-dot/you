import unittest

from helpers import fixture, read
from vshorts import intake, meta, probe, script


def four():
    raw = intake.detect(fixture("post-4-nahodki.txt"))
    parts = probe.select(probe.check_items(raw.items, offline=True))
    return raw, [c.item for c in parts[0]]


def codes(s, raw_text=""):
    return {i["code"] for i in script.lint(s, raw_text)}


class Build(unittest.TestCase):
    def test_skeleton_is_clean(self):
        raw, items = four()
        s = script.build(raw, items, noun="находка")
        self.assertEqual(script.errors(script.lint(s, raw.text)), [])
        self.assertEqual([b.kind for b in s.beats], ["hook", "item", "item", "item", "cta"])
        self.assertTrue(s.beats[0].say.startswith("Шпаргалка по Linux"), s.beats[0].say)
        self.assertNotIn("learn-anything", s.beats[0].say)
        self.assertEqual(s.beats[1].item["name"], "Мегашпаргалка по Linux")
        self.assertTrue(20 <= script.total(s) <= 40)
        self.assertEqual(s.subs["лёрн"], "learn-anything")
        self.assertEqual(s.subs["энисинг"], "")

    def test_cta_says_pinned_not_description(self):
        raw, items = four()
        cta = script.build(raw, items).beats[-1].say
        self.assertIn("в закрепе", cta)
        self.assertIn("BADVINO", cta)

    def test_series_cta(self):
        raw, items = four()
        s = script.build(raw, items, part=1, parts=2)
        self.assertIn("части 2", s.beats[-1].say)
        self.assertIn("ЧАСТЬ 1", s.beats[0].on_screen)

    def test_english_needs_model_script(self):
        raw, items = four()
        with self.assertRaises(ValueError):
            script.build(raw, items, lang="en")


class Lint(unittest.TestCase):
    def base(self):
        raw, items = four()
        return raw, script.build(raw, items)

    def test_greeting(self):
        raw, s = self.base()
        s.beats[0].say = "Привет, ребята! " + s.beats[0].say
        self.assertIn("E-GREETING", codes(s, raw.text))

    def test_filler(self):
        raw, s = self.base()
        s.beats[0].say = "В этом видео три сайта."
        self.assertIn("E-FILLER", codes(s, raw.text))

    def test_farewell(self):
        raw, s = self.base()
        s.beats[-1].say += " Всем пока!"
        self.assertIn("E-FAREWELL", codes(s, raw.text))

    def test_link_in_description(self):
        raw, s = self.base()
        s.beats[-1].say = "Ссылка в описании."
        self.assertIn("E-LINK-DESC", codes(s, raw.text))

    def test_invented_number(self):
        raw, s = self.base()
        s.beats[1].say += " Им пользуются 50000 человек."
        self.assertIn("E-NUMBER", codes(s, raw.text))

    def test_number_from_raw_is_fine(self):
        raw, s = self.base()
        s.beats[3].say = "Кэд сёрч. Ищет 3D-модели по описанию."
        self.assertNotIn("E-NUMBER", codes(s, raw.text))

    def test_cta_count_and_order(self):
        raw, s = self.base()
        s.beats.insert(1, script.Beat("cta0", "cta", "Подпишись.", ""))
        found = codes(s, raw.text)
        self.assertTrue({"E-CTA-COUNT", "E-CTA-EARLY"} & found)

    def test_too_long(self):
        raw, s = self.base()
        s.beats[1].seconds = 40
        self.assertIn("E-DURATION-LONG", codes(s, raw.text))

    def test_dash_and_emoji(self):
        raw, s = self.base()
        s.beats[1].say += " Удобно \u2014 очень."
        s.beats[1].on_screen += " 🔥"
        found = codes(s, raw.text)
        self.assertIn("E-DASH", found)
        self.assertIn("E-EMOJI-FRAME", found)

    def test_english_with_cyrillic(self):
        raw, s = self.base()
        s.lang = "en"
        self.assertIn("E-LANG", codes(s, raw.text))


    def test_reads_list_caught(self):
        raw, s = self.base()
        s.beats[1].say = "Шпаргалка. Файлы, процессы, права, память, сеть."
        self.assertIn("E-READS-LIST", codes(s, raw.text))

    def test_hook_list_caught(self):
        raw, s = self.base()
        names = [b.item["name"] for b in s.beats if b.item]
        s.beats[0].say = "Сайты: %s." % ", ".join(names)
        self.assertIn("E-HOOK-LIST", codes(s, raw.text))

    def test_normal_sentence_not_a_list(self):
        self.assertLess(script.list_run("Пишешь, что хочешь выучить, и получаешь готовый план: гайды, видео, роадмапы."), 4)
        self.assertGreaterEqual(script.list_run("База: файлы, процессы, права, память, сеть."), 4)

    def test_skeleton_never_reads_lists(self):
        import os
        from helpers import POSTS
        for name in os.listdir(POSTS):
            if not name[:4].isdigit():
                continue
            raw = intake.detect(read(os.path.join(POSTS, name)))
            if not raw.items:
                continue
            for item in raw.items:
                item.url = item.url or "https://example.dev/%d" % id(item)
            parts = probe.select(probe.check_items(raw.items, offline=True))
            if not parts:
                continue
            s = script.build(raw, [c.item for c in parts[0]])
            found = codes(s, raw.text)
            self.assertNotIn("E-READS-LIST", found, name)
            self.assertNotIn("E-HOOK-LIST", found, name)


class Captions(unittest.TestCase):
    def test_no_dangling_preposition(self):
        for chunk in meta.chunk_words("Описываешь деталь например шестерёнка с двенадцатью зубьями и получаешь сорок моделей"):
            self.assertNotIn(chunk.split()[-1].lower(), meta.STOP_TAIL, chunk)
            self.assertLessEqual(len(chunk.split()), 3)

    def test_enumeration_not_one_by_one(self):
        chunks = meta.chunk_words("База: файлы, процессы, права, память, сеть.")
        self.assertEqual(chunks, ["База:", "файлы, процессы,", "права, память,", "сеть."])

    def test_subs_applied(self):
        self.assertEqual(meta.apply_subs("Лёрн энисинг. Пишем тему.", {"Лёрн": "learn-anything", "энисинг": ""}),
                         "learn-anything. Пишем тему.")

    def test_srt_from_words(self):
        words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate("Пишешь тему и получаешь роадмап.".split())]
        srt = meta.srt_from_words(words, {})
        self.assertIn("00:00:00,000 --> ", srt)
        self.assertIn("роадмап.", srt)


if __name__ == "__main__":
    unittest.main()
