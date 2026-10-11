import unittest
import urllib.error

from helpers import fixture
from vshorts import intake, probe

BIG = "<html><title>Ok</title>" + "x" * 40000 + "</html>"


class Classify(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(probe.classify("u", 200, {}, BIG, "u").ok)

    def test_cloudflare_header(self):
        st = probe.classify("u", 403, {"cf-mitigated": "challenge"}, "<html></html>", "u")
        self.assertFalse(st.ok)
        self.assertIn("защитой", st.reason)

    def test_challenge_page_200(self):
        self.assertFalse(probe.classify("u", 200, {}, "<title>Just a moment...</title>" + "y" * 500, "u").ok)

    def test_weak_marker_on_live_page_is_fine(self):
        self.assertTrue(probe.classify("u", 200, {}, BIG.replace("x" * 10, "recaptcha", 1), "u").ok)

    def test_weak_marker_with_403_is_blocked(self):
        self.assertFalse(probe.classify("u", 403, {}, "<p>Access denied</p>", "u").ok)

    def test_down_and_404(self):
        self.assertIn("лежит", probe.classify("u", 502, {}, "", "u").reason)
        self.assertIn("404", probe.classify("u", 404, {}, "", "u").reason)


class Network(unittest.TestCase):
    def test_retry_then_ok(self):
        calls = []

        def fetch(url, timeout):
            calls.append(url)
            if len(calls) < 2:
                raise urllib.error.URLError("timeout")
            return 200, {}, BIG, url

        st = probe.check_site("https://x.dev", fetch=fetch, pause=0)
        self.assertTrue(st.ok)
        self.assertEqual(len(calls), 2)

    def test_gives_up(self):
        def fetch(url, timeout):
            raise urllib.error.URLError("dns")
        st = probe.check_site("https://x.dev", fetch=fetch, retries=1, pause=0)
        self.assertFalse(st.ok)
        self.assertIn("не отвечает", st.reason)

    def test_server_error_not_retried(self):
        calls = []

        def fetch(url, timeout):
            calls.append(1)
            return 503, {}, "", url
        probe.check_site("https://x.dev", fetch=fetch, pause=0)
        self.assertEqual(len(calls), 1)


class Select(unittest.TestCase):
    def test_four_finds_drop_blocked(self):
        raw = intake.detect(fixture("post-4-nahodki.txt"))
        checked = probe.check_items(raw.items, offline=True)
        verdicts = {c.item.name: c.verdict for c in checked}
        self.assertTrue(verdicts["builditapp"].startswith("пропущен"))
        parts = probe.select(checked)
        self.assertEqual(len(parts), 1)
        self.assertEqual([c.item.name for c in parts[0]], ["Мегашпаргалка по Linux", "learn-anything", "cad-search"])

    def test_series_split(self):
        items = [intake.Item("site%d" % i, "Бесплатно. Пишем запрос.", "https://s%d.dev" % i) for i in range(6)]
        parts = probe.select(probe.check_items(items, offline=True))
        self.assertEqual([len(p) for p in parts], [3, 3])

    def test_lonely_tail_glued(self):
        items = [intake.Item("site%d" % i, "", "https://s%d.dev" % i) for i in range(4)]
        parts = probe.select(probe.check_items(items, offline=True))
        self.assertEqual([len(p) for p in parts], [4])

    def test_missing_link_reported(self):
        checked = probe.check_items([intake.Item("NoLink", "x")], offline=True)
        self.assertIn("нет ссылки", checked[0].verdict)


if __name__ == "__main__":
    unittest.main()
