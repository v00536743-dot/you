import unittest

from helpers import fixture
from vshorts import intake, meta, metalint, prefs, probe


def facts(lang="ru"):
    raw = intake.detect(fixture("post-4-nahodki.txt"))
    items = [c.item.to_dict() for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
    return meta.facts_from(items, lang, True, noun="находка")


class Package(unittest.TestCase):
    def test_ru_package_clean(self):
        pkg = meta.package(facts(), prefs.template()["links"])
        self.assertEqual(metalint.lint(pkg), [])
        self.assertTrue(5 <= len(pkg["titles"]) <= 7)
        louds = [t["loudness"] for t in pkg["titles"]]
        self.assertEqual(louds, sorted(louds))
        self.assertEqual(sum(t["recommended"] for t in pkg["titles"]), 1)
        self.assertTrue(pkg["titles"][0]["text"].startswith("3 "))
        self.assertIn("#shorts", pkg["titles"][0]["text"])
        self.assertIn("https://t.me/VioraStudio", pkg["description"])
        self.assertLessEqual(len(pkg["pinned"].strip().splitlines()), 3)

    def test_en_package_clean(self):
        pkg = meta.package(facts("en"), prefs.template()["links"])
        self.assertEqual(metalint.lint(pkg), [])
        self.assertIn("Linux cheat sheet", pkg["titles"][4]["text"])

    def test_number_in_title_is_shown_count(self):
        pkg = meta.package(facts(), prefs.template()["links"])
        self.assertNotIn("4 ", pkg["titles"][0]["text"].split("#")[0])

    def test_history_moves_recommendation(self):
        quiet = {"chosen": ["бесплатные сайты для учёбы #shorts #a #b"] * 3}
        pkg = meta.package(facts(), prefs.template()["links"], quiet)
        rec = next(t for t in pkg["titles"] if t["recommended"])
        self.assertGreaterEqual(rec["loudness"], 4)

    def test_tag_limits(self):
        pkg = meta.package(facts(), prefs.template()["links"])
        self.assertLessEqual(len(meta.hashtag_sets(facts())["top"]), 3)
        self.assertLessEqual(len([w for w in pkg["tiktok"].split() if w.startswith("#")]), 5)


class Linter(unittest.TestCase):
    def test_selftest_cases(self):
        for name, data, code in metalint.selftest_cases():
            found = [i["code"] for i in metalint.lint(data) if i["level"] == "ERROR"]
            if code is None:
                self.assertEqual(found, [], name)
            else:
                self.assertIn(code, found, name)


if __name__ == "__main__":
    unittest.main()
