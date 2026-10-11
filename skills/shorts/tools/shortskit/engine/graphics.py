"""Graphics drawn by code in brand tokens: labels, CTA flash cards (handle, QR, text), bottom panel.

Text is always real font + flat colour + outline. Glow / gradient plates exist only behind brand.effects
(so QA bad-case tests can prove they are caught); they are never used by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import segno
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..util import contrast, fit_contrast, hex_to_rgb, snap8
from .brand import Brand
from .layout import Layout, Rect

LABEL_EM = 96
SERVICE_EM = 48


@dataclass
class Sprite:
    kind: str
    img: Image.Image  # RGBA
    box: Rect  # placement on the 1080x1920 frame at scale 1
    text: str = ""
    min_font: int = 0
    pairs: list[tuple[str, str, float]] = field(default_factory=list)  # (text colour, background, required ratio)
    url: str = ""
    qr_box: Rect | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "box": self.box.as_list(), "text": self.text, "min_font": self.min_font,
                "pairs": self.pairs, "url": self.url, "qr_box": self.qr_box.as_list() if self.qr_box else None}


def _font(path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, maxw: int, max_lines: int = 2) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.getlength(t) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:max_lines] if len(lines) <= max_lines else lines


def _fit_text(text: str, path, start: int, minimum: int, maxw: int, max_lines: int = 2):
    size = start
    while True:
        f = _font(path, size)
        lines = _wrap(text, f, maxw, max_lines)
        if (len(lines) <= max_lines and all(f.getlength(ln) <= maxw for ln in lines)) or size <= minimum:
            return f, lines, size
        size -= 4


def _glow(img: Image.Image, color: str) -> Image.Image:
    a = img.split()[3].filter(ImageFilter.GaussianBlur(14))
    halo = Image.new("RGBA", img.size, hex_to_rgb(color) + (0,))
    halo.putalpha(a.point(lambda v: min(255, int(v * 1.6))))
    return Image.alpha_composite(halo, img)


def _gradient(w: int, h: int) -> Image.Image:
    top, bot = np.array((124, 58, 237), float), np.array((37, 99, 235), float)
    k = np.linspace(0, 1, h)[:, None]
    rows = (top * (1 - k) + bot * k).astype(np.uint8)
    arr = np.repeat(rows[:, None, :], w, axis=1)
    return Image.fromarray(np.dstack([arr, np.full((h, w), 255, np.uint8)]), "RGBA")


def _text_layer(lines, font, fill: str, stroke: str | None, stroke_w: int, align_w: int, line_gap: int = 8):
    asc, desc = font.getmetrics()
    lh = asc + desc + line_gap
    h = lh * len(lines) + stroke_w * 2
    img = Image.new("RGBA", (align_w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        w = font.getlength(ln)
        d.text(((align_w - w) / 2, stroke_w + i * lh), ln, font=font, fill=fill,
               stroke_width=stroke_w if stroke else 0, stroke_fill=stroke)
    return img


def label(text: str, brand: Brand, lay: Layout) -> Sprite:
    t = text.upper() if brand.upper else text
    box = lay.label_box
    pad_x, pad_y = 32, 16
    f, lines, size = _fit_text(t, brand.display.path, LABEL_EM + 8, LABEL_EM, box.w - 2 * pad_x)
    if brand.label_style == "plate":
        txt_col = brand.bg if contrast(brand.bg, brand.accent) >= contrast(brand.fg, brand.accent) else brand.fg
        layer = _text_layer(lines, f, txt_col, None, 0, int(max(f.getlength(ln) for ln in lines)) + 4)
        w, h = layer.width + 2 * pad_x, layer.height + 2 * pad_y
        if brand.effects.get("gradient_plate"):
            img = _gradient(w, h)
        else:
            img = Image.new("RGBA", (w, h), hex_to_rgb(brand.accent) + (255,))
        img.alpha_composite(layer, (pad_x, pad_y))
        pairs = [(txt_col, brand.accent, 7.0)]
    else:
        stroke = brand.bg if contrast(brand.fg, brand.bg) > 3 else "#000000"
        img = _text_layer(lines, f, brand.fg, stroke, 8, int(max(f.getlength(ln) for ln in lines)) + 20)
        pairs = [(brand.fg, stroke, 7.0)]
    if brand.effects.get("text_glow"):
        img = _glow(img, brand.accent)
    cx = box.x + box.w // 2
    r = Rect(snap8(cx - img.width / 2), box.y, img.width, img.height)
    return Sprite("label", img, r, t, size, pairs)


def _card(content: Image.Image, bg: str, border: str, line_w: int, pad: int) -> Image.Image:
    w, h = content.width + 2 * pad, content.height + 2 * pad
    img = Image.new("RGBA", (w, h), hex_to_rgb(bg) + (255,))
    if line_w:
        ImageDraw.Draw(img).rectangle([0, 0, w - 1, h - 1], outline=hex_to_rgb(border) + (255,), width=line_w)
    img.alpha_composite(content, (pad, pad))
    return img


def _place_cta(img: Image.Image, lay: Layout, y: float | None) -> Rect:
    b = lay.cta_box
    cx = b.x + b.w // 2
    cy = int(y) if y is not None else b.y + b.h // 2
    return Rect(snap8(cx - img.width / 2), snap8(cy - img.height / 2), img.width, img.height)


def cta_handle(handle: str, link: str, brand: Brand, lay: Layout, y: float | None = None) -> Sprite:
    maxw = lay.cta_box.w - 2 * 48
    h_text = handle if handle.startswith("@") else f"@{handle}"
    f1, l1, s1 = _fit_text(h_text, brand.display.path, 96, 64, maxw, 1)
    link_col = fit_contrast(brand.accent, brand.bg, 4.5)
    parts = [_text_layer(l1, f1, brand.fg, None, 0, maxw)]
    pairs = [(brand.fg, brand.bg, 7.0)]
    sizes = [s1]
    if link:
        f2, l2, s2 = _fit_text(link, brand.body.path, 56, SERVICE_EM, maxw, 2)
        parts.append(_text_layer(l2, f2, link_col, None, 0, maxw))
        pairs.append((link_col, brand.bg, 4.5))
        sizes.append(s2)
    content = _stack(parts, 16)
    img = _card(content, brand.bg, brand.fg, brand.line_width, 40)
    if brand.effects.get("text_glow"):
        img = _glow(img, brand.accent)
    return Sprite("cta_handle", img, _place_cta(img, lay, y), f"{h_text} {link}".strip(), min(sizes), pairs)


def cta_text(text: str, brand: Brand, lay: Layout, y: float | None = None) -> Sprite:
    maxw = lay.cta_box.w - 2 * 48
    t = text.upper() if brand.upper else text
    f, lines, s = _fit_text(t, brand.display.path, 96, 64, maxw, 3)
    img = _card(_text_layer(lines, f, brand.fg, None, 0, maxw), brand.bg, brand.accent, brand.line_width, 40)
    if brand.effects.get("text_glow"):
        img = _glow(img, brand.accent)
    return Sprite("cta_text", img, _place_cta(img, lay, y), t, s, [(brand.fg, brand.bg, 7.0)])


def qr_image(url: str, size_px: int, dark: str, light: str, error: str = "q") -> tuple[Image.Image, int]:
    q = segno.make(url, error=error, micro=False)
    matrix = np.array([[bool(v) for v in row] for row in q.matrix], dtype=bool)
    n = matrix.shape[0] + 8  # 4-module quiet zone on each side
    mod = max(4, size_px // n)
    full = np.zeros((n, n), dtype=bool)
    full[4:-4, 4:-4] = matrix
    big = np.kron(full, np.ones((mod, mod), dtype=bool))
    d, li = np.array(hex_to_rgb(dark), np.uint8), np.array(hex_to_rgb(light), np.uint8)
    rgb = np.where(big[..., None], d, li)
    alpha = np.full(big.shape, 255, np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA"), mod


def cta_qr(url: str, link_text: str, brand: Brand, lay: Layout, y: float | None = None, qr_px: int = 432) -> Sprite:
    from ..util import luminance

    light, dark = (brand.fg, brand.bg) if luminance(hex_to_rgb(brand.fg)) > luminance(hex_to_rgb(brand.bg)) else (brand.bg, brand.fg)
    if contrast(light, dark) < 7:
        light, dark = "#FFFFFF", "#000000"
    maxw = lay.cta_box.w - 2 * 32
    avail_h = lay.cta_box.h - 2 * 32
    for px in range(qr_px, 359, -24):
        q, mod = qr_image(url, px, dark, light)
        f, lines, s = _fit_text(link_text, brand.body.path, 56, SERVICE_EM, maxw, 2)
        txt = _text_layer(lines, f, dark, None, 0, max(q.width, int(max(f.getlength(ln) for ln in lines)) + 8))
        content = _stack([q, txt], 8)
        if content.height <= avail_h and content.width <= maxw:
            break
    img = _card(content, light, dark, 0, 32)
    if brand.effects.get("text_glow"):
        img = _glow(img, brand.accent)
    box = _place_cta(img, lay, y)
    qx = box.x + 32 + (content.width - q.width) // 2
    qr_box = Rect(qx, box.y + 32, q.width, q.height)
    return Sprite("cta_qr", img, box, link_text, s, [(dark, light, 7.0)], url=url, qr_box=qr_box)


def _stack(parts: list[Image.Image], gap: int) -> Image.Image:
    w = max(p.width for p in parts)
    h = sum(p.height for p in parts) + gap * (len(parts) - 1)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for p in parts:
        img.alpha_composite(p, ((w - p.width) // 2, y))
        y += p.height + gap
    return img


def bottom_panel(rect: Rect, brand: Brand, handle: str, links: list[str], tagline: str = "", logo_path=None) -> Image.Image:
    img = Image.new("RGBA", (rect.w, rect.h), hex_to_rgb(brand.bg) + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, rect.w, brand.line_width - 1], fill=hex_to_rgb(brand.accent) + (255,))
    x = 64
    y = 40
    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((rect.h - 96, rect.h - 96))
        img.alpha_composite(logo, (x, (rect.h - logo.height) // 2))
        x += logo.width + 40
    word = brand.logo_text or (handle.lstrip("@").upper() if handle else "")
    if word:
        f = _font(brand.logo.path, 72)
        tracking = int(72 * brand.logo_tracking)
        cx = x
        for ch in word:
            d.text((cx, y), ch, font=f, fill=brand.fg)
            cx += f.getlength(ch) + tracking
        y += 96
        if brand.logo_sub:
            fs = _font(brand.logo.path, 28)
            cx = x + 4
            for ch in brand.logo_sub:
                d.text((cx, y - 8), ch, font=fs, fill=brand.fg)
                cx += fs.getlength(ch) + int(28 * 1.2)
            y += 40
    fb = _font(brand.body.path, 44)
    for line in [tagline, (links[0] if links else ""), (f"@{handle.lstrip('@')}" if handle and brand.logo_text else "")]:
        if line and y + 52 <= rect.h:
            d.text((x, y), line, font=fb, fill=brand.fg)
            y += 56
    return img
