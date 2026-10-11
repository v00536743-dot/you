import os
import shutil
import tempfile
import unittest

from helpers import drop, fixture, temp_skill
from vshorts import announce, cover, intake, meta, plan, probe


def facts(lang="ru"):
    raw = intake.detect(fixture("post-4-nahodki.txt"))
    items = [c.item.to_dict() for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
    return meta.facts_from(items, lang, True, noun="находка")


@unittest.skipUnless(cover.available(), "нет Pillow: обложки не рисуются, промпт проверяется отдельно")
class Covers(unittest.TestCase):
    def test_all_variants_pass_checks(self):
        out = tempfile.mkdtemp()
        try:
            for preset in ("viora", "mono"):
                rows = cover.render_set(facts(), plan.brand_tokens(preset), os.path.join(out, preset))
                self.assertEqual(len(rows), 4)
                for row in rows:
                    self.assertTrue(all(c["ok"] for c in row["checks"]), (preset, row))
                    self.assertTrue(os.path.exists(os.path.join(out, preset, row["file"])))
        finally:
            shutil.rmtree(out)

    def test_mono_is_grayscale(self):
        from PIL import Image
        out = tempfile.mkdtemp()
        try:
            cover.render_set(facts(), plan.brand_tokens("mono"), out)
            img = Image.open(os.path.join(out, "cover-punch.png")).convert("RGB")
            colors = img.getcolors(1 << 20)
            self.assertTrue(all(r == g == b for _, (r, g, b) in colors))
        finally:
            shutil.rmtree(out)

    def test_low_contrast_caught(self):
        layout = {"size": (1280, 720), "boxes": [], "texts": ["VIORA", "ДВА СЛОВА"], "headline_px": 120,
                  "palette": {"bg": "#000000", "fg": "#333333", "accent": "#E63946"}}
        bad = {c["id"]: c["ok"] for c in cover.checks(layout)}
        self.assertFalse(bad["contrast"])


class Prompt(unittest.TestCase):
    def test_prompt_forbids_text_and_slop(self):
        text = cover.prompt(facts(), plan.brand_tokens("viora"))
        for word in ("1280x720", "1080x1920", "Do NOT draw", "text", "gradients", "neon glow", "#E63946"):
            self.assertIn(word, text)


class Announce(unittest.TestCase):
    def setUp(self):
        self.root = temp_skill()

    def tearDown(self):
        drop(self.root)

    def test_announce_passes_strict_post_linter(self):
        text, issues = announce.best(facts(), 27, "https://www.youtube.com/@badVIno-VS/shorts", ["builditapp"], self.root)
        self.assertEqual(issues, [], text)
        self.assertIn("#шортс", text)
        self.assertIn("[ВИДЕО](https://www.youtube.com/@badVIno-VS/shorts)", text)
        self.assertNotIn("в описании", text.lower())
        self.assertTrue(text.rstrip().endswith("[ТГК](https://t.me/VioraStudio)"))


if __name__ == "__main__":
    unittest.main()
