import os
import unittest

from helpers import load_json, read, FIX, POSTS, fixture
from vshorts import intake


class PostBridge(unittest.TestCase):
    def test_four_finds_post(self):
        raw = intake.detect(fixture("post-4-nahodki.txt"))
        self.assertEqual(raw.kind, "post")
        self.assertEqual(raw.rubric, "сервисы")
        self.assertTrue(raw.hook.startswith("4 бесплатные находки"))
        names = [i.name for i in raw.items]
        self.assertEqual(names, ["Мегашпаргалка по Linux", "learn-anything", "cad-search", "builditapp"])
        by = {i.name: i for i in raw.items}
        self.assertEqual(by["learn-anything"].url, "https://learn-anything.xyz/")
        self.assertEqual(by["cad-search"].url, "https://www.cadlookup.com/")
        self.assertEqual(by["Мегашпаргалка по Linux"].url_from, "search")
        self.assertIn("Бесплатно", by["Мегашпаргалка по Linux"].lead)

    def test_real_post_five_sites(self):
        text = read(os.path.join(POSTS, "2026-09-5-poleznyh-saitov-i-skillov.md"))
        raw = intake.detect(text)
        self.assertEqual(raw.kind, "post")
        self.assertEqual([i.name for i in raw.items],
                         ["Emotion Direction", "AI UI Design от Google", "Photon", "Security Audit Skill от Cloudflare", "Inspo"])
        self.assertTrue(raw.items[0].lead.startswith("Готовые промпты"))
        self.assertTrue(raw.items[1].lead.startswith("Гайд по созданию"))
        self.assertIn("Установка: npx inspo-mcp install", raw.items[4].extra)
        # Ссылки в архиве поста вырезаны Телеграмом: честно без адреса.
        self.assertTrue(all(i.url is None for i in raw.items))

    def test_author_links_fill_missing(self):
        text = read(os.path.join(POSTS, "2026-09-5-poleznyh-saitov-i-skillov.md"))
        raw = intake.detect(text, links={"Photon": "https://example.org/photon"})
        photon = next(i for i in raw.items if i.name == "Photon")
        self.assertEqual((photon.url, photon.url_from), ("https://example.org/photon", "author"))

    def test_every_archived_post_parses(self):
        for name in os.listdir(POSTS):
            if name.endswith(".md") and name[:4].isdigit():
                raw = intake.detect(read(os.path.join(POSTS, name)))
                self.assertIn(raw.kind, ("post", "text"), name)

    def test_markdown_links_in_post(self):
        raw = intake.detect("2 находки.\n\n1. [Alpha](https://alpha.dev). Делает схемы.\n\n[Beta](https://beta.dev).\n- Пишет код.\n\n#сервисы\n")
        self.assertEqual([(i.name, i.url) for i in raw.items], [("Alpha", "https://alpha.dev"), ("Beta", "https://beta.dev")])


class Kinds(unittest.TestCase):
    def test_links_list(self):
        raw = intake.detect("https://learn-anything.xyz/ роадмапы\nhttps://www.cadlookup.com/\n")
        self.assertEqual(raw.kind, "links")
        self.assertEqual(raw.items[0].name, "learn-anything")
        self.assertEqual(raw.items[0].lead, "роадмапы")

    def test_html_and_video(self):
        self.assertEqual(intake.detect(os.path.join(FIX, "mini-film.html")).kind, "html")
        self.assertEqual(intake.detect("https://youtu.be/abc").kind, "video")

    def test_plain_text(self):
        raw = intake.detect("Почему одна идея на ролик работает лучше. Потому что зритель держит одну мысль.")
        self.assertEqual(raw.kind, "text")


if __name__ == "__main__":
    unittest.main()
