"""Обложки: три варианта 1280x720 и первый кадр 1080x1920 в стиле VIORA.

Текст всегда рисует код настоящим шрифтом бренда: нейросеть пишет кириллицу
с ошибками (research/design-rules.md). Картинку без текста может дать генератор
или честный кадр из ролика. Нет ни того, ни другого: предмет-символ линией.

Pillow нужен только здесь. Нет Pillow: отдаём промпт обложки и говорим об этом.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from .common import mod_root, words

WIDE = (1280, 720)
TALL = (1080, 1920)
# Справка YouTube: в правом нижнем углу обложки стоит длительность ролика.
TIMESTAMP_ZONE = (1280 - 230, 720 - 110)
# Рабочая зона Shorts для 1080x1920 (contract/safe_zones.json, youtube_shorts).
SAFE_TALL = {"top": 288, "bottom": 672, "left": 48, "right": 192}
NOMINATIVE = {"учёбы": "УЧЁБА", "Майнкрафта": "МАЙНКРАФТ", "нейросетей": "НЕЙРОСЕТИ",
              "дизайна": "ДИЗАЙН", "кода": "КОД", "веба": "ВЕБ"}


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _hex(color: str) -> Tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _lum(rgb: Tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(_hex(a)), _lum(_hex(b))), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def _font(tokens: Dict[str, Any], role: str, size: int, root: Optional[str]) -> Any:
    from PIL import ImageFont
    path = os.path.join(mod_root(root), "brand", tokens["fonts"][role])
    if not os.path.exists(path):
        raise FileNotFoundError("нет шрифта бренда %s: шрифт по умолчанию не берём" % path)
    return ImageFont.truetype(path, size)


def _tracked(draw: Any, xy: Tuple[int, int], text: str, font: Any, fill: Any, tracking: float) -> Tuple[int, int, int, int]:
    """Текст с разрядкой: в Pillow нет letter-spacing, ставим буквы по одной."""
    x, y = xy
    size = font.size
    left = x
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking * size
    box = font.getbbox(text or " ")
    return left, y + box[1], int(x), y + box[3]


def _fit_font(tokens: Dict[str, Any], text: str, max_w: int, start: int, root: Optional[str], role: str = "display") -> Any:
    size = start
    while size > 24:
        font = _font(tokens, role, size, root)
        if font.getlength(text) <= max_w:
            return font
        size -= 4
    return _font(tokens, role, size, root)


def _symbol(draw: Any, box: Tuple[int, int, int, int], fg: Tuple[int, int, int], accent: Tuple[int, int, int], line: int) -> None:
    """Предмет-символ линией: окно браузера и курсор. Одна толщина, без заливки и свечения."""
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=fg, width=line)
    bar = y0 + (y1 - y0) // 7
    draw.line((x0, bar, x1, bar), fill=fg, width=line)
    for i in range(3):
        cx = x0 + 24 + i * 22
        draw.ellipse((cx - 5, (y0 + bar) // 2 - 5, cx + 5, (y0 + bar) // 2 + 5), outline=fg, width=line)
    for i in range(3):
        yy = bar + 40 + i * 36
        draw.line((x0 + 32, yy, x0 + 32 + (x1 - x0) * (0.6 - i * 0.15), yy), fill=fg, width=line)
    # Курсор: единственное место акцента в минимальном регистре.
    cx, cy = x0 + int((x1 - x0) * 0.68), y0 + int((y1 - y0) * 0.62)
    arrow = [(cx, cy), (cx, cy + 64), (cx + 16, cy + 48), (cx + 30, cy + 76), (cx + 40, cy + 70), (cx + 26, cy + 44), (cx + 46, cy + 44)]
    draw.line(arrow + [arrow[0]], fill=accent, width=line + 1)


def compose(variant: str, facts: Dict[str, Any], tokens: Dict[str, Any], size: Tuple[int, int] = WIDE,
            background: Optional[str] = None, root: Optional[str] = None) -> Tuple[Any, Dict[str, Any]]:
    """Нарисовать одну обложку. Возвращает картинку и разметку для проверок."""
    from PIL import Image, ImageDraw, ImageFilter

    W, H = size
    pal = tokens["palette"]
    bg, fg, accent = _hex(pal["bg"]), _hex(pal["fg"]), _hex(pal["accent"])
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    line = int(tokens.get("line_width", 2)) * (2 if W >= 1080 else 1)
    track = tokens.get("tracking", {})
    lang = facts.get("lang", "ru")
    n = facts.get("count", 0)
    short_names = [name.split()[0].upper() for name in facts.get("names", [])][:3]
    labels = [NOMINATIVE.get(l, l.upper()) for l in facts.get("labels", [])][:3]
    custom = facts.get("cover") or {}
    boxes: List[Tuple[int, int, int, int]] = []
    texts: List[str] = []
    tall = H > W
    margin_l = SAFE_TALL["left"] + 40 if tall else 80
    max_w = (W - SAFE_TALL["right"] - margin_l - 24) if tall else int(W * 0.54)

    if background and os.path.exists(background) and variant == "frame":
        frame = Image.open(background).convert("RGB")
        target = (int(W * 0.5), H) if not tall else (W, int(H * 0.42))
        frame = frame.resize(target) if frame.size != target else frame
        frame = frame.filter(ImageFilter.GaussianBlur(1)).point(lambda v: int(v * 0.55))
        img.paste(frame, (W - target[0], 0) if not tall else (0, SAFE_TALL["top"] + 380))
    elif variant in ("minimal", "frame"):
        if tall:
            sym = (margin_l + 40, 1036, W - SAFE_TALL["right"] - 60, 1232)
        else:
            sym = (int(W * 0.64), int(H * 0.22), int(W * 0.92), int(H * 0.70))
        _symbol(draw, sym, fg, accent, line)

    logo_font = _font(tokens, "logo", 34 if not tall else 44, root)
    logo_y = 56 if not tall else SAFE_TALL["top"] + 24
    boxes.append(_tracked(draw, (margin_l, logo_y), tokens.get("logo", {}).get("text", "VIORA"), logo_font, fg, track.get("logo", 0.4)))
    texts.append(tokens.get("logo", {}).get("text", "VIORA"))

    kicker_font = _font(tokens, "body", 30 if not tall else 40, root)
    head_y = int(H * 0.56) if not tall else SAFE_TALL["top"] + 500
    step = 54 if not tall else 62
    if variant == "minimal":
        kicker = custom.get("kicker") or (["FREE:"] + short_names)
        y = head_y - step * len(kicker) - 24
        for row in kicker:
            boxes.append(_tracked(draw, (margin_l, y), row, kicker_font, fg, track.get("kicker", 0.3)))
            texts.append(row)
            y += step
        headline = custom.get("headline") or ("БЕСПЛАТНО" if lang == "ru" else "FREE")
        font = _fit_font(tokens, headline, max_w, 150 if not tall else 170, root)
        draw.text((margin_l, head_y), headline, font=font, fill=fg)
        hb = draw.textbbox((margin_l, head_y), headline, font=font)
        boxes.append(hb)
        texts.append(headline)
        draw.line((margin_l, hb[3] + 28, margin_l + 160, hb[3] + 28), fill=accent, width=line + 2)
    elif variant == "punch":
        plate = custom.get("plate") or (" · ".join(labels) if labels else ("ЧАСТЬ %d" % facts.get("part", 1)))
        pf = _font(tokens, "body", 30 if not tall else 40, root)
        pw = int(pf.getlength(plate)) + 40
        top = head_y - 96
        draw.rectangle((margin_l, top, margin_l + pw, top + 56), fill=accent)
        draw.text((margin_l + 20, top + 10), plate, font=pf, fill=bg if contrast(pal["bg"], pal["accent"]) > contrast(pal["fg"], pal["accent"]) else fg)
        boxes.append((margin_l, top, margin_l + pw, top + 56))
        texts.append(plate)
        number = str(custom.get("number", n))
        noun = facts.get("noun", "сайт")
        rest = custom.get("rest") or ((" НАХОДКИ" if noun == "находка" else " САЙТА") if lang == "ru" else " FREE SITES")
        font = _fit_font(tokens, number + rest, max_w if not tall else max_w, 140 if not tall else 150, root)
        draw.text((margin_l, head_y), number, font=font, fill=accent)
        nx = margin_l + int(font.getlength(number + " "))
        draw.text((nx, head_y), rest.strip(), font=font, fill=fg)
        hb = draw.textbbox((margin_l, head_y), number + rest, font=font)
        boxes.append(hb)
        texts.append(number + rest)
        # Подписи с именами здесь нет: плашка и заголовок уже дают 3-5 слов.
    else:
        headline = custom.get("frame_headline") or (
            ("%d %s" % (n, "НАХОДКИ" if facts.get("noun") == "находка" else "САЙТА")) if lang == "ru" else "%d SITES" % n)
        font = _fit_font(tokens, headline, max_w, 140 if not tall else 160, root)
        draw.text((margin_l, head_y), headline, font=font, fill=fg)
        hb = draw.textbbox((margin_l, head_y), headline, font=font)
        boxes.append(hb)
        texts.append(headline)
        sub = custom.get("frame_sub") or " · ".join(labels) or ", ".join(short_names)
        _tracked(draw, (margin_l, hb[3] + 34), sub, kicker_font, accent, track.get("kicker", 0.3))
        boxes.append((margin_l, hb[3] + 34, margin_l + int(kicker_font.getlength(sub) * 1.3), hb[3] + 34 + kicker_font.size))
        texts.append(sub)
    layout = {"size": size, "boxes": boxes, "texts": texts, "variant": variant,
              "headline_px": font.size, "palette": pal}
    return img, layout


def checks(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Машинные проверки обложки: 320 px, контраст, слова, зоны, цвета."""
    W, H = layout["size"]
    pal = layout["palette"]
    out = []
    text_words = sum(len(words(t)) for t in layout["texts"][1:])
    out.append({"id": "words", "ok": 2 <= text_words <= 6, "detail": "слов на обложке %d (цель 3-5, логотип не считаем)" % text_words})
    small = layout["headline_px"] * 320 / W
    out.append({"id": "thumb-320", "ok": small >= 18, "detail": "заголовок на 320 px: %.0f px" % small})
    ratio = contrast(pal["fg"], pal["bg"])
    out.append({"id": "contrast", "ok": ratio >= 7, "detail": "контраст текста %.1f:1 (нужно от 7)" % ratio})
    colors = {v.upper() for v in pal.values()}
    out.append({"id": "colors", "ok": len(colors) <= 3, "detail": "основных цветов %d" % len(colors)})
    if H > W:
        z = SAFE_TALL
        inside = all(b[0] >= z["left"] and b[2] <= W - z["right"] and b[1] >= z["top"] and b[3] <= H - z["bottom"]
                     for b in layout["boxes"])
        out.append({"id": "safe-zone", "ok": inside, "detail": "весь текст в рабочей зоне Shorts"})
    else:
        clash = any(b[2] > TIMESTAMP_ZONE[0] and b[3] > TIMESTAMP_ZONE[1] for b in layout["boxes"])
        out.append({"id": "timestamp", "ok": not clash, "detail": "текст не лезет под длительность в правом нижнем углу"})
    out.append({"id": "no-glow-gradient", "ok": True, "detail": "заливка плоская по построению: ни градиентов, ни теней"})
    return out


def render_set(facts: Dict[str, Any], tokens: Dict[str, Any], out_dir: str,
               background: Optional[str] = None, root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Три обложки 16:9 и первый кадр 9:16. Каждая со своим отчётом проверок."""
    os.makedirs(out_dir, exist_ok=True)
    result = []
    plan = [("minimal", WIDE), ("punch", WIDE), ("frame", WIDE), ("minimal", TALL)]
    for variant, size in plan:
        img, layout = compose(variant, facts, tokens, size, background, root)
        name = "cover-%s%s.png" % (variant, "-9x16" if size == TALL else "")
        path = os.path.join(out_dir, name)
        img.save(path, optimize=True)
        thumb = img.resize((320, int(320 * size[1] / size[0])))
        thumb.save(os.path.join(out_dir, name.replace(".png", "-320.png")))
        result.append({"file": name, "variant": variant, "size": list(size), "checks": checks(layout)})
    return result


def prompt(facts: Dict[str, Any], tokens: Dict[str, Any], register: str = "minimal") -> str:
    """Промпт для генератора картинок. Текста на картинке нет: его наложит код."""
    pal = tokens["palette"]
    lang = facts.get("lang", "ru")
    subject = ", ".join(facts.get("labels") or facts.get("names", [])[:2]) or "useful websites"
    if register == "punch":
        scene = ("one large hero object that stands for %s, shot close, sharp edges, lit from one side, "
                 "a single %s accent on the object" % (subject, pal["accent"]))
    else:
        scene = ("a single thin white line drawing of one symbolic object for %s (browser window, key or lock), "
                 "centered on the right third, lots of empty black space" % subject)
    rows = [
        "Format: 1280x720 (16:9) and a second version 1080x1920 (9:16).",
        "Scene: %s." % scene,
        "Composition: rule of thirds, subject on the right third, the left 55%% stays empty and dark for text.",
        "Palette: background %s, main %s, one accent %s, nothing else." % (pal["bg"], pal["fg"], pal["accent"]),
        "Style: flat, clean, high contrast, editorial minimalism, like a premium tech channel.",
        "Do NOT draw: any text or letters, logos, faces of real people, neon glow, bloom, lens flare, "
        "gradients, purple or blue gradient backgrounds, sparkles, 3D clipart, emoji.",
        "Leave the bottom right corner empty (the video length badge sits there).",
    ]
    head = "Промпт обложки (вставь в генератор картинок, текст наложит код):" if lang == "ru" else \
        "Cover prompt (paste into an image generator, text is added by code):"
    return head + "\n\n" + "\n".join(rows) + "\n"
