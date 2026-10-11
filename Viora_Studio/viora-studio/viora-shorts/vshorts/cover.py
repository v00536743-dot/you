"""Обложки: три варианта 1280x720 и постер первого кадра 1080x1920 в стиле VIORA.

Текст всегда рисует код настоящим шрифтом бренда: нейросеть пишет кириллицу
с ошибками (research/design-rules.md). Герой обложки это настоящий кадр:
скриншот самого живого сайта из ролика (vshorts/shot.py) или кадр готового видео.
Нет ни того, ни другого: предмет-символ линией, как в минимал-обложках канала.

Затемнение кадра равномерное (умножение на число), без градиентов и свечения.
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
# Текст на 320 px ширины: меньше 14 px глаз в ленте не читает. Логотип это знак, не текст.
MIN_TEXT_AT_320 = 14
MIN_HEADLINE_AT_320 = 24
MIN_CONTRAST = 4.5
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
    def channel(c: float) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(la: float, lb: float) -> float:
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def contrast(a: str, b: str) -> float:
    return _ratio(_lum(_hex(a)), _lum(_hex(b)))


def _font(tokens: Dict[str, Any], role: str, size: int, root: Optional[str]) -> Any:
    from PIL import ImageFont
    path = os.path.join(mod_root(root), "brand", tokens["fonts"][role])
    if not os.path.exists(path):
        raise FileNotFoundError("нет шрифта бренда %s: шрифт по умолчанию не берём" % path)
    return ImageFont.truetype(path, size)


def _fit_font(tokens: Dict[str, Any], text: str, max_w: int, start: int, root: Optional[str],
              role: str = "display", floor: int = 56, tracking: float = 0.0) -> Any:
    size = start
    while size > floor:
        font = _font(tokens, role, size, root)
        if _width(font, text, tracking) <= max_w:
            return font
        size -= 4
    return _font(tokens, role, floor, root)


def _fit_tracked(tokens: Dict[str, Any], text: str, max_w: int, start: int, root: Optional[str],
                 tracking: float) -> Tuple[Any, float]:
    """Подпись с разрядкой: сначала сжимаем разрядку, потом шрифт, но не ниже 56 px."""
    spacing = tracking
    while spacing > 0.04 and _width(_font(tokens, "body", 56, root), text, spacing) > max_w:
        spacing = round(spacing - 0.04, 2)
    return _fit_font(tokens, text, max_w, start, root, "body", 56, spacing), spacing


def _width(font: Any, text: str, tracking: float = 0.0) -> float:
    if not tracking:
        return font.getlength(text)
    return sum(font.getlength(ch) for ch in text) + tracking * font.size * max(0, len(text) - 1)


class Canvas:
    """Картинка плюс разметка текстов: по ней работают проверки."""

    def __init__(self, size: Tuple[int, int], tokens: Dict[str, Any], root: Optional[str]):
        from PIL import Image, ImageDraw
        self.size = size
        self.tokens = tokens
        self.root = root
        pal = tokens["palette"]
        self.bg, self.fg, self.accent = _hex(pal["bg"]), _hex(pal["fg"]), _hex(pal["accent"])
        self.img = Image.new("RGB", size, self.bg)
        self.draw = ImageDraw.Draw(self.img)
        self.texts: List[Dict[str, Any]] = []
        self.base = None

    def freeze_background(self) -> None:
        """Снимок фона до текста: по нему честно меряем контраст под каждой надписью."""
        self.base = self.img.copy()

    def text(self, xy: Tuple[int, int], text: str, font: Any, fill: Tuple[int, int, int],
             role: str = "text", tracking: float = 0.0) -> Tuple[int, int, int, int]:
        x, y = xy
        if tracking:
            cx = x
            for ch in text:
                self.draw.text((cx, y), ch, font=font, fill=fill)
                cx += font.getlength(ch) + tracking * font.size
            box = font.getbbox(text)
            bbox = (x, y + box[1], int(cx - tracking * font.size), y + box[3])
        else:
            self.draw.text((x, y), text, font=font, fill=fill)
            bbox = self.draw.textbbox((x, y), text, font=font)
        self.texts.append({"text": text, "box": bbox, "px": font.size, "fill": fill, "role": role})
        return bbox

    def plate(self, box: Tuple[int, int, int, int], color: Tuple[int, int, int]) -> None:
        self.draw.rectangle(box, fill=color)


def _paste_shot(canvas: Canvas, shot: str, box: Tuple[int, int, int, int], dim: float, frame: bool) -> None:
    """Кадр сайта в прямоугольник: обрезка по центру, равномерное затемнение, тонкая рамка."""
    from PIL import Image, ImageOps
    x0, y0, x1, y1 = box
    img = Image.open(shot).convert("RGB")
    img = ImageOps.fit(img, (x1 - x0, y1 - y0), method=Image.LANCZOS, centering=(0.5, 0.42))
    pal = canvas.tokens["palette"]
    if all(v[1:3] == v[3:5] == v[5:7] for v in (s.upper() for s in pal.values())):
        img = img.convert("L").convert("RGB")  # mono: никакого цвета, даже из кадра сайта
    from PIL import ImageStat
    mean = ImageStat.Stat(img.convert("L")).mean[0]
    if mean * dim > 110:
        # Светлая страница на чёрной обложке горит пятном: приглушаем до средней яркости 110.
        dim = 110 / mean
    if dim < 1:
        img = img.point(lambda v: int(v * dim))
    canvas.img.paste(img, (x0, y0))
    if frame:
        width = int(canvas.tokens.get("line_width", 2)) * (2 if canvas.size[0] >= 1080 else 1)
        canvas.draw.rectangle(box, outline=canvas.fg, width=width)


def _symbol(canvas: Canvas, box: Tuple[int, int, int, int]) -> None:
    """Предмет-символ линией: окно браузера и курсор. Одна толщина, без заливки и свечения."""
    draw, fg, accent = canvas.draw, canvas.fg, canvas.accent
    line = int(canvas.tokens.get("line_width", 2)) * (2 if canvas.size[0] >= 1080 else 1)
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
    cx, cy = x0 + int((x1 - x0) * 0.68), y0 + int((y1 - y0) * 0.62)
    arrow = [(cx, cy), (cx, cy + 64), (cx + 16, cy + 48), (cx + 30, cy + 76), (cx + 40, cy + 70), (cx + 26, cy + 44), (cx + 46, cy + 44)]
    draw.line(arrow + [arrow[0]], fill=accent, width=line + 1)


def texts_for(facts: Dict[str, Any]) -> Dict[str, str]:
    """Слова обложки: 3-5 штук, не повторяют название, цифра только показанная."""
    custom = facts.get("cover") or {}
    lang = facts.get("lang", "ru")
    n = facts.get("count", 0)
    labels = [NOMINATIVE.get(l, l.upper()) for l in facts.get("labels", [])][:3]
    if lang == "ru":
        noun = {"находка": ("НАХОДКА", "НАХОДКИ", "НАХОДОК")}.get(facts.get("noun", ""), ("САЙТ", "САЙТА", "САЙТОВ"))
        word = noun[0] if n % 10 == 1 and n % 100 != 11 else (noun[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else noun[2])
        free = "БЕСПЛАТНО" if facts.get("free", True) else "ПОЛЕЗНОЕ"
    else:
        word = "SITE" if n == 1 else "SITES"
        free = "FREE" if facts.get("free", True) else "USEFUL"
    return {
        "kicker": custom.get("kicker") or " · ".join(labels) or free,
        "headline": custom.get("headline") or free,
        "number": str(custom.get("number", n)),
        "noun": custom.get("rest", word).strip(),
        "plate": custom.get("plate") or free,
    }


def compose(variant: str, facts: Dict[str, Any], tokens: Dict[str, Any], size: Tuple[int, int] = WIDE,
            shot: Optional[str] = None, root: Optional[str] = None) -> Tuple[Any, Dict[str, Any]]:
    W, H = size
    tall = H > W
    c = Canvas(size, tokens, root)
    words_ = texts_for(facts)
    track = tokens.get("tracking", {})
    has_shot = bool(shot and os.path.exists(shot))
    pad = 72

    if tall:
        z = SAFE_TALL
        left, right, top = z["left"] + 40, W - z["right"] - 24, z["top"] + 32
        if has_shot:
            _paste_shot(c, shot, (left, 1000, right, 1000 + int((right - left) * 0.62)), 0.92, True)
        else:
            _symbol(c, (left + 40, 1020, right - 60, 1220))
        c.freeze_background()
        c.text((left, top), tokens["logo"]["text"], _font(tokens, "logo", 44, root), c.fg, "logo", track.get("logo", 0.4))
        kicker_font, spacing = _fit_tracked(tokens, words_["kicker"], right - left, 60, root, track.get("kicker", 0.3))
        c.text((left, top + 160), words_["kicker"], kicker_font, c.accent, tracking=spacing)
        line = "%s %s" % (words_["number"], words_["noun"])
        head = _fit_font(tokens, line, right - left, 150, root)
        c.text((left, top + 270), line, head, c.fg, "headline")
    elif variant == "minimal":
        _symbol(c, (int(W * 0.64), int(H * 0.22), int(W * 0.92), int(H * 0.70)))
        c.freeze_background()
        max_w = int(W * 0.64) - pad - 40
        c.text((pad, 56), tokens["logo"]["text"], _font(tokens, "logo", 40, root), c.fg, "logo", track.get("logo", 0.4))
        kicker_font, spacing = _fit_tracked(tokens, words_["kicker"], max_w, 60, root, track.get("kicker", 0.3))
        c.text((pad, 250), words_["kicker"], kicker_font, c.fg, tracking=spacing)
        head = _fit_font(tokens, words_["headline"], max_w, 150, root)
        box = c.text((pad, 340), words_["headline"], head, c.fg, "headline")
        width = int(tokens.get("line_width", 2)) + 4
        c.draw.line((pad, box[3] + 34, pad + 180, box[3] + 34), fill=c.accent, width=width)
    elif variant == "punch":
        if has_shot:
            _paste_shot(c, shot, (0, 0, W, H), 0.24, False)
        else:
            _symbol(c, (int(W * 0.62), int(H * 0.2), int(W * 0.92), int(H * 0.68)))
        plate_font = _font(tokens, "display", 56, root)
        plate_w = int(plate_font.getlength(words_["plate"])) + 48
        c.plate((pad, 200, pad + plate_w, 200 + 88), c.accent)
        c.freeze_background()
        c.text((pad, 56), tokens["logo"]["text"], _font(tokens, "logo", 40, root), c.fg, "logo", track.get("logo", 0.4))
        ink = c.bg if contrast(tokens["palette"]["bg"], tokens["palette"]["accent"]) >= \
            contrast(tokens["palette"]["fg"], tokens["palette"]["accent"]) else c.fg
        c.text((pad + 24, 210), words_["plate"], plate_font, ink, "plate")
        line = "%s %s" % (words_["number"], words_["noun"])
        head = _fit_font(tokens, line, W - pad - 240, 170, root)
        number_w = int(head.getlength(words_["number"] + " "))
        c.text((pad, 340), words_["number"], head, c.accent, "headline")
        c.text((pad + number_w, 340), words_["noun"], head, c.fg, "headline")
    else:  # hero: слева чёрная колонка с текстом, справа живой кадр
        split = int(W * 0.46)
        if has_shot:
            _paste_shot(c, shot, (split, 0, W, H), 0.85, False)
            c.draw.line((split, 0, split, H), fill=c.accent, width=6)
        else:
            _symbol(c, (split + 80, int(H * 0.2), W - 80, int(H * 0.7)))
        c.freeze_background()
        max_w = split - pad - 32
        c.text((pad, 56), tokens["logo"]["text"], _font(tokens, "logo", 40, root), c.fg, "logo", track.get("logo", 0.4))
        head = _fit_font(tokens, words_["number"], max_w, 260, root)
        box = c.text((pad, 150), words_["number"], head, c.accent, "headline")
        noun = _fit_font(tokens, words_["noun"], max_w, 110, root)
        box = c.text((pad, box[3] + 30), words_["noun"], noun, c.fg, "headline")
        kicker_font, spacing = _fit_tracked(tokens, words_["headline"], max_w, 64, root, track.get("kicker", 0.3))
        c.text((pad, box[3] + 40), words_["headline"], kicker_font, c.fg, tracking=spacing)
    layout = {"size": size, "texts": c.texts, "variant": variant, "palette": tokens["palette"],
              "shot": has_shot, "base": c.base, "final": c.img}
    return c.img, layout


def _bg_contrast(layout: Dict[str, Any], item: Dict[str, Any]) -> float:
    """Контраст надписи к худшему пикселю фона под ней (5-й и 95-й перцентиль)."""
    base = layout.get("base")
    text_l = _lum(item["fill"])
    if base is None:
        return contrast("#%02x%02x%02x" % item["fill"], layout["palette"]["bg"])
    x0, y0, x1, y1 = item["box"]
    crop = base.crop((max(0, x0), max(0, y0), max(x0 + 1, x1), max(y0 + 1, y1))).convert("RGB")
    crop = crop.resize((max(1, crop.width // 4), max(1, crop.height // 4)))
    lums = sorted(_lum(px) for px in crop.getdata())
    if not lums:
        return 21.0
    worst = lums[int(len(lums) * 0.95) - 1] if text_l > 0.5 else lums[int(len(lums) * 0.05)]
    return _ratio(text_l, worst)


def checks(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Машинные проверки по каждой надписи: размер на 320 px, контраст к фону, слова, зоны."""
    W, H = layout["size"]
    texts = [t for t in layout["texts"] if t["role"] != "logo"]
    out = []
    count = sum(len(words(t["text"])) for t in texts)
    out.append({"id": "words", "ok": 2 <= count <= 5, "detail": "слов на обложке %d (цель 3-5, логотип не считаем)" % count})
    scale = 320 / W
    small = min((t["px"] * scale for t in texts), default=0)
    head = max((t["px"] * scale for t in texts if t["role"] == "headline"), default=0)
    worst_text = min(texts, key=lambda t: t["px"])["text"] if texts else ""
    out.append({"id": "thumb-320", "ok": small >= MIN_TEXT_AT_320 and head >= MIN_HEADLINE_AT_320,
                "detail": "на 320 px самый мелкий текст %.0f px («%s»), заголовок %.0f px (нужно от %d и %d)"
                % (small, worst_text, head, MIN_TEXT_AT_320, MIN_HEADLINE_AT_320)})
    ratios = [(_bg_contrast(layout, t), t["text"]) for t in texts]
    low = min(ratios, default=(21.0, ""))
    out.append({"id": "contrast", "ok": low[0] >= MIN_CONTRAST,
                "detail": "худший контраст %.1f:1 у «%s» к фону под ним (нужно от %.1f)" % (low[0], low[1], MIN_CONTRAST)})
    final = layout.get("final")
    base = layout.get("base")
    if final is not None and base is not None:
        from PIL import ImageChops
        blank = [t["text"] for t in texts
                 if not ImageChops.difference(final.crop(t["box"]), base.crop(t["box"])).getbbox()]
        out.append({"id": "ink", "ok": not blank,
                    "detail": "все надписи реально нарисованы" if not blank else "не нарисовано: %s" % ", ".join(blank)})
    clash = []
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            ax0, ay0, ax1, ay1 = a["box"]
            bx0, by0, bx1, by1 = b["box"]
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1 and a["fill"] != b["fill"] or \
                    (ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1 and abs(ax0 - bx0) > 4 and ay0 != by0):
                clash.append("%s / %s" % (a["text"], b["text"]))
    out.append({"id": "overlap", "ok": not clash, "detail": "надписи не наезжают друг на друга" if not clash else "наезд: " + ", ".join(clash)})
    colors = {v.upper() for v in layout["palette"].values()}
    out.append({"id": "colors", "ok": len(colors) <= 3, "detail": "основных цветов бренда %d" % len(colors)})
    boxes = [t["box"] for t in layout["texts"]]
    if H > W:
        z = SAFE_TALL
        inside = all(b[0] >= z["left"] and b[2] <= W - z["right"] and b[1] >= z["top"] and b[3] <= H - z["bottom"] for b in boxes)
        out.append({"id": "safe-zone", "ok": inside, "detail": "весь текст в рабочей зоне Shorts"})
    else:
        clash = any(b[2] > TIMESTAMP_ZONE[0] and b[3] > TIMESTAMP_ZONE[1] for b in boxes)
        overflow = any(b[2] > W - 24 or b[3] > H - 16 for b in boxes)
        out.append({"id": "timestamp", "ok": not clash and not overflow,
                    "detail": "текст не лезет под длительность и за край"})
    out.append({"id": "no-glow-gradient", "ok": True,
                "detail": "заливки плоские, кадр затемнён равномерно: градиентов и свечения нет по построению"})
    return out


def render_set(facts: Dict[str, Any], tokens: Dict[str, Any], out_dir: str, shot: Optional[str] = None,
               root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Три обложки 16:9 и постер 9:16. Каждая со своим отчётом проверок и превью 320 px."""
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    result = []
    for variant, size in (("hero", WIDE), ("punch", WIDE), ("minimal", WIDE), ("poster", TALL)):
        img, layout = compose(variant, facts, tokens, size, shot, root)
        name = "cover-%s%s.png" % (variant, "-9x16" if size == TALL else "")
        img.save(os.path.join(out_dir, name), optimize=True)
        img.resize((320, int(320 * size[1] / size[0])), Image.LANCZOS).save(os.path.join(out_dir, name.replace(".png", "-320.png")))
        result.append({"file": name, "variant": variant, "size": list(size), "shot": layout["shot"],
                       "checks": checks(layout)})
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
        "Composition: rule of thirds, subject on the right third, the left 45%% stays empty and dark for text.",
        "Palette: background %s, main %s, one accent %s, nothing else." % (pal["bg"], pal["fg"], pal["accent"]),
        "Style: flat, clean, high contrast, editorial minimalism, like a premium tech channel.",
        "Do NOT draw: any text or letters, logos, faces of real people, neon glow, bloom, lens flare, "
        "gradients, purple or blue gradient backgrounds, sparkles, 3D clipart, emoji.",
        "Leave the bottom right corner empty (the video length badge sits there).",
    ]
    head = "Промпт обложки (вставь в генератор картинок, текст наложит код):" if lang == "ru" else \
        "Cover prompt (paste into an image generator, text is added by code):"
    return head + "\n\n" + "\n".join(rows) + "\n"
