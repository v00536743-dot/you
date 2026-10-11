"""Word-level captions: spoken->written substitutions, chunking by meaning, ASS karaoke, SRT.

Rules (COMMON.md 6): 2-3 words per chunk split by meaning, current word in the accent colour (flat, no glow),
outline instead of shadow, >= 64 px, inside the lower third of the safe zone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import ImageFont

from ..util import ass_color, fix_dashes
from .brand import Brand
from .layout import Layout

FUNCTION_WORDS = {
    "ru": set("в во на с со к ко по о об обо у из за от до для при про без над под перед через и а но или да же ли бы не ни что чтобы как то это его её их мой твой наш ваш свой этот тот".split()),
    "en": set("a an the to of in on at by for with from into onto and or but nor so if as than that this these those my your our their his her its not no is are was were be".split()),
}
NUM_WORDS = re.compile(r"^(\d+[\d.,]*|один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|сто|тысяча|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)$", re.I)
STRONG = re.compile(r"[.!?\u2026]+[\"')»]*$")
MEDIUM = re.compile(r"[,;:\-]+[\"')»]*$")
MIN_EM = 64
DEFAULT_EM = 72
SIDE_PAD = 24
OUTLINE = 6


@dataclass
class Chunk:
    words: list[dict]
    lines: int = 1
    size: int = DEFAULT_EM
    box: list[int] = field(default_factory=list)
    overflow: bool = False

    @property
    def start(self) -> float:
        return self.words[0]["s"]

    @property
    def end(self) -> float:
        return self.words[-1]["e"]

    @property
    def text(self) -> str:
        return " ".join(w["w"] for w in self.words)


def core(word: str) -> str:
    return re.sub(r"[^\w\-]", "", word.lower())


def apply_subs(words: list[dict], subs: dict[str, str]) -> list[dict]:
    """Replace how the synthesizer reads a word with how it is written. Empty value drops the word."""
    if not subs:
        return [dict(w) for w in words]
    table = {tuple(k.lower().split()): v for k, v in subs.items()}
    maxlen = max(len(k) for k in table)
    out: list[dict] = []
    i = 0
    while i < len(words):
        done = False
        for n in range(min(maxlen, len(words) - i), 0, -1):
            key = tuple(core(w["w"]) for w in words[i:i + n])
            if key in table:
                val = table[key]
                tail = re.search(r"[^\w\-]+$", words[i + n - 1]["w"])
                tail_s = tail.group(0) if tail else ""
                if val == "":
                    if out:
                        out[-1]["e"] = words[i + n - 1]["e"]
                        out[-1]["w"] += tail_s
                else:
                    out.append({"w": val + tail_s, "s": words[i]["s"], "e": words[i + n - 1]["e"]})
                i += n
                done = True
                break
        if not done:
            out.append(dict(words[i]))
            i += 1
    return out


@lru_cache(maxsize=32)
def _pil_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def text_width(text: str, font_path: str, size: int) -> int:
    return int(_pil_font(font_path, size).getlength(text))


def chunk_words(words: list[dict], lang: str, max_words: int, fits) -> list[list[dict]]:
    """Dynamic programming over split points; cost favours punctuation/pauses, punishes dangling function words."""
    fw = FUNCTION_WORDS.get(lang[:2], set())
    n = len(words)
    INF = float("inf")
    best = [INF] * (n + 1)
    prev = [0] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] == INF:
            continue
        for j in range(i + 1, min(n, i + max_words) + 1):
            ch = words[i:j]
            text = " ".join(w["w"] for w in ch)
            if len(ch) > 1 and not fits(text):
                break
            c = 0.0
            for w in ch[:-1]:
                if STRONG.search(w["w"]):
                    c += 8
                elif MEDIUM.search(w["w"]):
                    c += 2.5
            last = ch[-1]["w"]
            if j < n:
                pause = words[j]["s"] - ch[-1]["e"]
                if STRONG.search(last):
                    c -= 3
                elif MEDIUM.search(last):
                    c -= 2
                elif pause >= 0.6:
                    c -= 2.5
                elif pause >= 0.3:
                    c -= 1
                else:
                    c += 1
                if core(last) in fw:
                    c += 6
                if NUM_WORDS.match(core(last)) and not MEDIUM.search(last) and not STRONG.search(last):
                    c += 4
            size_cost = {1: 2.5, 2: 0.0, 3: 0.2}.get(len(ch), 1.5)
            if len(ch) == 1 and (STRONG.search(last) or len(core(last)) >= 10):
                size_cost = 0.5
            c += size_cost
            if ch[-1]["e"] - ch[0]["s"] < 0.35:
                c += 1.5
            if best[i] + c < best[j]:
                best[j] = best[i] + c
                prev[j] = i
    out, j = [], n
    while j > 0:
        i = prev[j]
        out.append(words[i:j])
        j = i
    return out[::-1]


def build(words: list[dict], brand: Brand, layout: Layout, cfg: dict, lang: str) -> list[Chunk]:
    words = [dict(w, w=fix_dashes(w["w"])) for w in words if w["w"].strip()]
    if not words:
        return []
    upper = cfg.get("upper", brand.upper)
    em = max(MIN_EM, int(cfg.get("size", DEFAULT_EM)))
    font = str(brand.display.path)
    maxw = layout.caption_band.w - 2 * SIDE_PAD

    def disp(t: str) -> str:
        return t.upper() if upper else t

    def fits(t: str) -> bool:
        return text_width(disp(t), font, em) <= maxw

    groups = chunk_words(words, lang, int(cfg.get("max_words", 3)), fits)
    chunks = []
    for g in groups:
        ch = Chunk(g, size=em)
        t = disp(ch.text)
        size = em
        while text_width(t, font, size) > maxw and size > MIN_EM:
            size -= 4
        ch.size = size
        width = text_width(t, font, size)
        if width > maxw:
            if len(g) > 1:
                ch.lines = 2
                half = (len(g) + 1) // 2
                l1, l2 = disp(" ".join(w["w"] for w in g[:half])), disp(" ".join(w["w"] for w in g[half:]))
                width = max(text_width(l1, font, size), text_width(l2, font, size))
            ch.overflow = width > maxw
        chunks.append(ch)
    place(chunks, brand, layout, cfg)
    return chunks


def place(chunks: list[Chunk], brand: Brand, layout: Layout, cfg: dict) -> None:
    band = layout.caption_band
    cx = band.x + band.w // 2
    bottom = int(cfg["y"]) if cfg.get("y") is not None else band.y1 - 32
    upper = cfg.get("upper", brand.upper)
    for ch in chunks:
        line_h = brand.display.ass_size(ch.size)
        if ch.lines == 1:
            w = text_width(ch.text.upper() if upper else ch.text, str(brand.display.path), ch.size)
        else:
            half = (len(ch.words) + 1) // 2
            parts = [" ".join(x["w"] for x in ch.words[:half]), " ".join(x["w"] for x in ch.words[half:])]
            w = max(text_width(p.upper() if upper else p, str(brand.display.path), ch.size) for p in parts)
        h = line_h * ch.lines
        ch.box = [cx - w // 2 - OUTLINE, bottom - h - OUTLINE, cx + w // 2 + OUTLINE, bottom + OUTLINE]


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def to_ass(chunks: list[Chunk], brand: Brand, cfg: dict, total: float) -> str:
    upper = cfg.get("upper", brand.upper)
    hl = cfg.get("highlight", "accent") != "none"
    fam = brand.display.family
    base_size = brand.display.ass_size(chunks[0].size if chunks else DEFAULT_EM)
    head = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{fam},{base_size},{ass_color(brand.caption_fill)},{ass_color(brand.caption_accent)},"
        f"{ass_color(brand.caption_outline)},{ass_color('#000000', 0xFF)},0,0,0,0,100,100,0,0,1,{OUTLINE},0,2,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fill, acc = ass_color(brand.caption_fill), ass_color(brand.caption_accent)
    lines = []
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1].start if ci + 1 < len(chunks) else total
        ch_end = min(nxt, ch.end + 0.35)
        x = (ch.box[0] + ch.box[2]) // 2
        y = ch.box[3] - OUTLINE
        size = brand.display.ass_size(ch.size)
        half = (len(ch.words) + 1) // 2 if ch.lines == 2 else None
        for wi, w in enumerate(ch.words):
            s = ch.start if wi == 0 else w["s"]
            e = ch.words[wi + 1]["s"] if wi + 1 < len(ch.words) else ch_end
            if e - s < 0.02:
                continue
            parts = []
            for k, ww in enumerate(ch.words):
                t = _esc(ww["w"].upper() if upper else ww["w"])
                if hl and k == wi:
                    t = "{\\u1}" + t + "{\\u0}" if brand.highlight_mode == "underline" else "{\\1c" + acc + "}" + t + "{\\1c" + fill + "}"
                if half is not None and k == half:
                    parts.append("\\N")
                parts.append(t)
            body = " ".join(parts).replace(" \\N ", "\\N")
            pop = "\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{\\an2\\pos({x},{y})\\fs{size}{pop}}}{body}")
    return "\n".join(head + lines) + "\n"


def _srt_ts(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(words: list[dict], max_chars: int = 42) -> str:
    lines, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["w"] for x in cur)
        if STRONG.search(w["w"]) or len(text) >= max_chars:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    out = []
    for i, ln in enumerate(lines, 1):
        out.append(f"{i}\n{_srt_ts(ln[0]['s'])} --> {_srt_ts(ln[-1]['e'] + 0.2)}\n{' '.join(x['w'] for x in ln)}\n")
    return "\n".join(out)
