import copy
import json
import os
import unittest

from helpers import load_json, read, FIX, MOD, fixture
from vshorts import html_adapter, intake, plan, prefs, probe, schema, script

TG = "https://t.me/VioraStudio"


def eff(**over):
    data = prefs.template()
    data.update(over)
    return prefs.effective(data)


def build(**over):
    raw = intake.detect(fixture("post-4-nahodki.txt"))
    items = [c.item for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
    s = script.build(raw, items)
    return plan.build(s, eff(**over), raw, base_dir="/tmp/out"), s


def codes(p, qr=TG):
    return {i["code"] for i in schema.full_check(p, expect_qr_url=qr, known_presets=plan.known_presets())}


class Schema(unittest.TestCase):
    def test_contract_example_is_valid(self):
        example = load_json(os.path.join(MOD, "contract", "plan.example.json"))
        self.assertEqual(schema.validate(example, schema.load_schema()), [])

    def test_contract_copy_matches_repo_spec(self):
        spec = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(MOD))), "viora-v8", "spec")
        if not os.path.isdir(spec):
            self.skipTest("viora-v8/spec рядом нет: скилл распакован отдельно")
        for name in ("plan.schema.json", "plan.example.json", "safe_zones.json"):
            self.assertEqual(load_json(os.path.join(spec, name)),
                             load_json(os.path.join(MOD, "contract", name)), name)

    def test_validator_catches_basics(self):
        bad = {"schema_version": "2", "meta": {"name": "Bad Name", "language": "r", "platforms": []},
               "layout": {"mode": "two"}, "brand": {}, "scenes": []}
        errors = schema.validate(bad, schema.load_schema())
        text = "\n".join(errors)
        for needle in ("schema_version", "meta.name", "meta.language", "meta.platforms", "layout.mode",
                       "brand: нет обязательного поля preset", "scenes: элементов меньше 1"):
            self.assertIn(needle, text)

    def test_agrees_with_jsonschema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema не установлен")
        sch = schema.load_schema()
        good, _ = build()
        bad = copy.deepcopy(good)
        bad["layout"]["cta_in_center"] = bad["layout"]["cta_in_center"] * 2
        bad["captions"]["max_words"] = 9
        for doc in (good, bad):
            ours = schema.validate(doc, sch) == []
            theirs = jsonschema.Draft202012Validator(sch).is_valid(doc)
            self.assertEqual(ours, theirs)


class Bridge(unittest.TestCase):
    def test_four_finds_plan_clean(self):
        p, s = build()
        found = schema.full_check(p, expect_qr_url=TG, known_presets=plan.known_presets())
        self.assertEqual([i for i in found if i["level"] == "ERROR"], [])
        self.assertEqual(p["brand"]["preset"], "viora")
        self.assertEqual(p["captions"]["max_words"], 3)
        self.assertTrue(p["meta"]["loop"])
        self.assertEqual(p["scenes"][-1]["source"]["ref"], p["scenes"][0]["source"]["ref"])
        kinds = [c["kind"] for c in p["layout"]["cta_in_center"]]
        self.assertEqual(kinds, ["handle", "qr"])
        qr = p["layout"]["cta_in_center"][-1]
        self.assertEqual(qr["url"], TG)
        self.assertEqual(qr["text"], "t.me/VioraStudio")
        self.assertTrue(p["brand"]["fonts"]["display"].endswith("Montserrat-ExtraBold.ttf"))

    def test_no_top_footage_degrades_and_reminds(self):
        p, _ = build(layout="three")
        self.assertEqual(p["layout"]["mode"], "center_bottom")
        self.assertIn("top", p["x_viora"]["pending"])

    def test_with_top_footage_three_panels(self):
        data = prefs.template()
        data["layout"] = "three"
        data["panels"]["top"]["source"] = "assets/footage/game.mp4"
        raw = intake.detect(fixture("post-4-nahodki.txt"))
        items = [c.item for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
        p = plan.build(script.build(raw, items), prefs.effective(data), raw)
        self.assertEqual(p["layout"]["mode"], "three")
        self.assertEqual(p["layout"]["top"]["height_pct"] + p["layout"]["bottom"]["height_pct"], 38)

    def test_every_layout_mode(self):
        for mode in prefs.MODES:
            data = prefs.template()
            data["layout"] = mode
            data["panels"]["top"]["source"] = "game.mp4"
            raw = intake.detect(fixture("post-4-nahodki.txt"))
            items = [c.item for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
            p = plan.build(script.build(raw, items), prefs.effective(data), raw)
            self.assertEqual(p["layout"]["mode"], mode)
            self.assertNotIn("E-CENTER", codes(p))

    def test_slop_words_in_captions(self):
        good, _ = build()
        doc = copy.deepcopy(good)
        doc["captions"]["style"] = "neon gradient"
        self.assertIn("E-SLOP", codes(doc))
        self.assertNotIn("E-SLOP", codes(good))

    def test_top_panel_html(self):
        data = prefs.template()
        data["layout"] = "three"
        data["panels"]["top"]["source"] = "html:" + os.path.join(FIX, "top-loop.html")
        raw = intake.detect(fixture("post-4-nahodki.txt"))
        items = [c.item for c in probe.select(probe.check_items(raw.items, offline=True))[0]]
        p = plan.build(script.build(raw, items), prefs.effective(data), raw, base_dir=FIX)
        self.assertEqual(p["layout"]["top"]["source"], "html:top-loop.html")
        self.assertEqual([i for i in schema.full_check(p, expect_qr_url=TG, known_presets=plan.known_presets())
                          if i["level"] == "ERROR"], [])

    def test_sfx_files_exist_for_names(self):
        p, _ = build()
        names = {x["name"] for s in p["scenes"] for x in s.get("sfx", [])}
        folder = os.path.join(MOD, "assets", "audio", "sfx")
        for name in names:
            self.assertTrue(os.path.exists(os.path.join(folder, name + ".wav")), name)

    def test_mono_preset(self):
        p, _ = build(brand={"preset": "mono", "register": "minimal"})
        self.assertEqual(p["captions"]["highlight"], "none")
        self.assertNotIn("E-MONO-COLOR", codes(p))

    def test_events_every_three_seconds(self):
        p, _ = build()
        for scene in p["scenes"]:
            times = sorted([0.0] + [a["t"] for a in scene["source"]["actions"] if "t" in a] + [scene["x_duration_hint"]])
            self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 3.05, scene["id"])

    def test_known_crash_avoided(self):
        p, _ = build()
        cad = next(s for s in p["scenes"] if "cadlookup" in s["source"]["ref"] and s["id"].startswith("item"))
        self.assertFalse(any(a["do"] == "click" for a in cad["source"]["actions"]))
        self.assertTrue(cad["x_avoid"])


class Rules(unittest.TestCase):
    def test_bad_cases(self):
        good, _ = build()
        cases = {
            "E-CENTER": lambda p: p["layout"].update(mode="three", top={"height_pct": 30, "source": "a.mp4"}),
            "E-TOP-EMPTY": lambda p: p["layout"].update(mode="three", top={"height_pct": 20}),
            "E-TOP-SLOP": lambda p: p["layout"].update(mode="three", top={"height_pct": 20, "source": "gradient-balls.mp4"}),
            "E-CTA-MANY": lambda p: p["layout"]["cta_in_center"].extend([{"t": 1, "kind": "text", "text": "x", "duration": 2}] * 2),
            "E-CTA-OVERLAP": lambda p: p["layout"]["cta_in_center"].append({"t": p["layout"]["cta_in_center"][0]["t"] + 1, "duration": 2, "kind": "text", "text": "x"}),
            "E-QR-URL": lambda p: p["layout"]["cta_in_center"][-1].update(url="https://example.com"),
            "E-QR-MISSING": lambda p: p["layout"]["cta_in_center"].pop(),
            "E-QR-NO-TEXT": lambda p: p["layout"]["cta_in_center"][-1].pop("text"),
            "E-COLORS": lambda p: p["brand"]["palette"].update(extra="#123456"),
            "E-FONT-DEFAULT": lambda p: p["brand"]["fonts"].update(display="/usr/share/fonts/DejaVuSans.ttf"),
            "E-MONO-COLOR": lambda p: p["brand"].update(preset="mono"),
            "E-LUFS": lambda p: p["audio"].update(target_lufs=-9),
            "E-DASH": lambda p: p["scenes"][1].update(say="Сайт \u2014 огонь"),
            "E-SCENE-ID": lambda p: p["scenes"][2].update(id=p["scenes"][1]["id"]),
            "E-DURATION": lambda p: p["scenes"][1].update(x_duration_hint=40),
            "E-CAPTION-WORDS": lambda p: p["captions"].update(max_words=4),
            "E-SLOP": lambda p: p["brand"].update(effects={"text_glow": 12}),
            "E-TOP-COLOR": lambda p: p["layout"].update(mode="three", top={"height_pct": 20, "source": "color:#111111"}),
        }
        for code, mutate in cases.items():
            doc = copy.deepcopy(good)
            mutate(doc)
            self.assertIn(code, codes(doc), code)


class Html(unittest.TestCase):
    def setUp(self):
        self.info = html_adapter.inspect(os.path.join(FIX, "mini-film.html"))

    def test_inspect(self):
        self.assertEqual(self.info.title, "Ночной рейс")
        self.assertTrue(self.info.seek_hook and self.info.has_webaudio and self.info.needs_click)
        self.assertFalse(self.info.needs_network)
        self.assertEqual(self.info.duration, 12.0)
        self.assertEqual([c.title for c in self.info.chapters], ["Корабль выходит из порта", "Айсберг в темноте", "Огни на воде"])
        self.assertEqual(html_adapter.best_window(self.info)[0], 4.0)

    def test_speed_map(self):
        sp = html_adapter.parse_speed("0-4:1.5,4-8:0.6,8-12:2")
        self.assertAlmostEqual(html_adapter.output_length(0, 12, sp), 4 / 1.5 + 4 / 0.6 + 4 / 2, places=2)
        self.assertAlmostEqual(html_adapter.output_length(2, 6, sp), 2 / 1.5 + 2 / 0.6, places=2)
        self.assertEqual(html_adapter.output_length(0, 3, []), 3.0)
        with self.assertRaises(ValueError):
            html_adapter.parse_speed("0-4:9")

    def test_capture_modes(self):
        page = html_adapter.capture_action(self.info, "page", 0, 4)
        self.assertEqual((page["mode"], page["sound"]), ("realtime", "page"))
        self.assertTrue(page["start_click"])
        quiet = html_adapter.capture_action(self.info, "sfx", 0, 4)
        self.assertEqual(quiet["mode"], "deterministic")

    def test_html_plan(self):
        sp = html_adapter.parse_speed("0-4:1.5,4-8:0.6,8-12:2")
        s = script.build_html(self.info, "ru", sp)
        p = plan.build(s, eff(), None, html_info=self.info, sound="page", speed_map=sp, base_dir=FIX)
        self.assertEqual(p["layout"]["mode"], "center_only")
        self.assertTrue(all(sc["source"]["type"] == "html" for sc in p["scenes"]))
        self.assertEqual(p["scenes"][0]["source"]["ref"], "mini-film.html")
        found = schema.full_check(p, expect_qr_url=TG, known_presets=plan.known_presets())
        self.assertEqual([i for i in found if i["level"] == "ERROR"], [])
        chapter2 = next(sc for sc in p["scenes"] if sc["id"] == "chapter-2")
        self.assertEqual(chapter2["speed"][0]["rate"], 0.6)


if __name__ == "__main__":
    unittest.main()
