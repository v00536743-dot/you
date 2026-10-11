from shortskit.engine import brand as B
from shortskit.engine import captions as C
from shortskit.engine import layout as L


def words(text: str, step: float = 0.3, pause_after: dict | None = None):
    out, t = [], 0.1
    for i, w in enumerate(text.split()):
        out.append({"w": w, "s": round(t, 3), "e": round(t + step * 0.85, 3)})
        t += step + (pause_after or {}).get(i, 0)
    return out


def build(text, lang="ru", platforms=("youtube_shorts",), **kw):
    br = B.resolve({"preset": "viora"}, None, lang)
    lay = L.compute({"mode": "three"}, list(platforms))
    return C.build(words(text, **kw), br, lay, {"max_words": 3}, lang), br, lay


def test_chunks_are_2_to_3_words_and_not_cut_after_preposition():
    chunks, _, _ = build("Описываешь деталь обычными словами, например шестерёнка с двенадцатью зубьями, и получаешь сорок моделей.")
    texts = [c.text for c in chunks]
    assert all(1 <= len(c.words) <= 3 for c in chunks)
    assert not any(t.split()[-1].lower() in ("с", "и", "в", "на") for t in texts[:-1]), texts
    assert "например шестерёнка с" not in [t.lower() for t in texts]
    assert sum(len(c.words) for c in chunks) / len(chunks) >= 2


def test_punctuation_ends_a_chunk():
    chunks, _, _ = build("Первый сайт. Второй сайт тоже бесплатный.")
    assert chunks[0].text.endswith(".")


def test_no_overflow_with_tiktok_column():
    chunks, _, lay = build("Невероятно длинноесловодлясубтитров и ещё немного текста здесь", platforms=("youtube_shorts", "tiktok"))
    for c in chunks:
        assert c.box[0] >= lay.safe.rect.x - 8 and c.box[2] <= lay.caption_band.x1 + 8 or c.overflow


def test_subs_replace_spoken_with_written():
    w = words("Первый лёрн энисинг и кэд лукап")
    out = C.apply_subs(w, {"лёрн энисинг": "learn-anything", "кэд лукап": "CAD Lookup"})
    assert [x["w"] for x in out] == ["Первый", "learn-anything", "и", "CAD Lookup"]
    assert out[1]["s"] == w[1]["s"] and out[1]["e"] == w[2]["e"]
    dropped = C.apply_subs(words("лёрн энисинг тут"), {"лёрн": "learn-anything", "энисинг": ""})
    assert [x["w"] for x in dropped] == ["learn-anything", "тут"]


def test_ass_highlights_current_word_flat_no_blur():
    chunks, br, _ = build("Два бесплатных сайта")
    ass = C.to_ass(chunks, br, {"highlight": "accent"}, 3.0)
    assert "\\1c" in ass
    assert "\\blur" not in ass and "\\be" not in ass
    style = [ln for ln in ass.splitlines() if ln.startswith("Style:")][0].split(",")
    assert style[17].strip() == "0"  # shadow 0, outline instead
    assert int(style[16]) >= 4
    n_words = sum(len(c.words) for c in chunks)
    assert ass.count("Dialogue:") == n_words


def test_caption_size_and_contrast():
    chunks, br, _ = build("Тест размера")
    assert all(c.size >= 64 for c in chunks)
    from shortskit.util import contrast

    assert contrast(br.caption_accent, br.caption_outline) >= 7
    assert contrast(br.caption_fill, br.caption_outline) >= 7


def test_srt():
    srt = C.to_srt(words("Раз два три. Четыре пять."))
    assert srt.startswith("1\n00:00:00,100 --> ")
    assert "\n\n2\n" in srt


def test_english_chunks():
    chunks, _, _ = build("Two free sites and you will use both of them today.", lang="en")
    assert not any(c.text.split()[-1].lower() in ("and", "of", "the") for c in chunks[:-1])
