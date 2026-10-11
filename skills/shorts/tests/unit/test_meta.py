from shortskit import memory as M
from shortskit.meta import packaging as PK
from shortskit.util import count_emoji, has_long_dash

from conftest import mini_plan


def manifest(lang="ru"):
    return {"name": "mini", "language": lang, "platforms": ["youtube_shorts", "tiktok"]}


def test_auto_draft_meets_template():
    plan = mini_plan()
    plan["scenes"][0]["say"] = "Два бесплатных сайта \u2014 и оба пригодятся."
    plan["layout"]["bottom"] = {"links": ["https://t.me/VioraStudio"]}
    d = PK.auto_draft(plan, manifest(), "ru")
    m = PK.build(plan, manifest(), d, M.load())
    assert not m["errors"], m["errors"]
    assert 5 <= len(m["titles"]) <= 7
    assert all(t["chars"] <= 100 and count_emoji(t["title"]) <= 1 for t in m["titles"])
    assert [t["loudness"] for t in m["titles"]] == sorted(t["loudness"] for t in m["titles"])
    assert all("#shorts" in t["hashtags"] for t in m["titles"])
    lines = m["description"].splitlines()
    assert lines[0].count("#") <= 3 and lines[0].startswith("#")
    assert "Telegram: https://t.me/VioraStudio" in m["description"]
    assert lines[-1].startswith("#")
    assert len(m["pinned_comment"]) == 3
    assert m["tiktok_caption"].count("#") <= 5
    assert not has_long_dash(m["description"] + " ".join(t["title"] for t in m["titles"]))


def test_links_are_never_invented():
    plan = mini_plan()
    m = PK.build(plan, manifest(), PK.auto_draft(plan, manifest(), "ru"), M.load())
    assert "http" not in m["description"]
    assert any("no links" in w for w in m["warnings"])


def test_rules_catch_bad_titles():
    plan = mini_plan()
    draft = {"titles": [{"text": "A" * 120, "loudness": 1}, {"text": "КАПС В СПОКОЙНОМ ВАРИАНТЕ", "loudness": 4},
                        {"text": "two emoji \U0001F631\U0001F631", "loudness": 2}], "summary": "x"}
    m = PK.build(plan, manifest(), draft, M.load())
    errs = " ".join(m["errors"])
    assert "chars" in errs and "caps" in errs and "emoji" in errs and "need 5-7" in errs


def test_english_template():
    plan = mini_plan()
    plan["meta"]["language"] = "en"
    plan["scenes"][0]["say"] = "Two free sites you will use."
    plan["scenes"][0]["on_screen_text"] = "2 FREE SITES"
    m = PK.build(plan, manifest("en"), PK.auto_draft(plan, manifest("en"), "en"), M.load())
    assert not m["errors"] and "Full video on the channel." in m["description"]


def test_spoken_form_is_written_in_texts():
    assert PK.written("Один эйч ти эм эл файл", {"эйч ти эм эл": "HTML"}) == "Один HTML файл"
