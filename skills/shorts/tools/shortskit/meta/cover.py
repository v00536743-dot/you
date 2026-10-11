"""Covers (COMMON.md 8, research 2.1/2.2/7, design-rules).

The image may come from a model (if a generator is configured), from the user (--image), or from an honest frame
of the video (always available). TEXT IS ALWAYS DRAWN BY CODE with the brand font.
Three variants, each in 1280x720 and 1080x1920:
  A "punch":   frame full-bleed, accent plate label with the text on the free third
  B "minimal": brand background, the frame as a window with a thin line, big caps text, one accent word
  C "outline": frame full-bleed, darkened flat, big outlined text
Checks per cover: 3-5 words, readable at 320 px, text contrast >= 4.5:1 on real pixels, not in the
time-stamp corner (16:9) / inside the safe zone (9:16), no gradient, silhouette test (grey + blur).
If no generator: DIR/cover/prompt.md has a ready prompt for the user (and the frame covers are still made).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..engine import brand as B
from ..engine.layout import safe_zone
from ..util import contrast, hex_to_rgb, log, read_json, rgb_to_hex, write_json
from ..qa import frames as F

SIZES = {"16x9": (1280, 720), "9x16": (1080, 1920)}


# ---------------------------------------------------------------- generator detection (names only, never values)

def generator() -> str | None:
    forced = os.environ.get("SHORTS_IMAGE_PROVIDER")
    if forced in ("none", "off"):
        return None
    if forced:
        return forced
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return None


def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
        return json.loads(r.read())


def generate_image(prompt: str, out: Path, provider: str, landscape: bool = True) -> Path:
    """Not verified in CI (needs a key). Image only, no text in the prompt result."""
    if provider == "openai":
        data = _post("https://api.openai.com/v1/images/generations",
                     {"model": os.environ.get("SHORTS_OPENAI_IMAGE_MODEL", "gpt-image-1"), "prompt": prompt,
                      "size": "1536x1024" if landscape else "1024x1536", "n": 1},
                     {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        out.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
    elif provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
        model = os.environ.get("SHORTS_GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"contents": [{"parts": [{"text": prompt}]}]}, {"x-goog-api-key": key})
        parts = data["candidates"][0]["content"]["parts"]
        img = next(p for p in parts if "inlineData" in p or "inline_data" in p)
        blob = img.get("inlineData") or img.get("inline_data")
        out.write_bytes(base64.b64decode(blob["data"]))
    else:
        raise ValueError(f"unknown image provider {provider}")
    return out


def prompt_text(manifest: dict, plan: dict, words: str, lang: str) -> str:
    br = manifest["brand"]
    pal = br["palette"]
    topic = (plan.get("metadata") or {}).get("topic") or words
    emotion = plan["meta"].get("emotion") or br.get("emotion_default", "trust")
    ru = lang == "ru"
    lines = [
        ("# Промпт для обложки" if ru else "# Cover prompt"), "",
        ("Сгенерируй картинку БЕЗ ТЕКСТА (текст я наложу кодом)." if ru else "Generate an image WITH NO TEXT (text is added by code)."), "",
        "```",
        f"Subject: one hero object that stands for \"{topic}\", large, clear silhouette, honest to the video content.",
        "Composition: rule of thirds, hero on the right third, the left third calm and dark for a headline. Lots of negative space.",
        f"Palette: background {pal['bg']}, main {pal['fg']}, ONE accent {pal['accent']}. Flat colour, high contrast, at most 3 colours.",
        f"Mood: {emotion}. Style: minimal editorial product photo or clean line illustration.",
        "Do NOT draw: any text or letters, logos, neon glow, light leaks, purple-blue gradients, bokeh orbs, lens flares,",
        "cinematic teal-orange grading, sparkles, emoji, faces of real people, busy collage.",
        "Formats: 1280x720 (16:9) and 1080x1920 (9:16) with the hero above the middle.",
        "```", "",
        ("Готовую картинку дай мне файлом, я запущу: `python3 tools/shorts.py cover DIR --image файл.png`"
         if ru else "Send the image back and run: `python3 tools/shorts.py cover DIR --image file.png`"),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- composition helpers

def _cover_fit(img: np.ndarray, w: int, h: int, fx: float = 0.5, fy: float = 0.5) -> np.ndarray:
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    r = cv2.resize(img, (max(w, int(iw * s + 0.5)), max(h, int(ih * s + 0.5))), interpolation=cv2.INTER_AREA)
    x0 = int((r.shape[1] - w) * fx)
    y0 = int((r.shape[0] - h) * fy)
    return r[y0:y0 + h, x0:x0 + w]


def saliency_x(img: np.ndarray) -> float:
    """Horizontal centre of visual mass (edges), 0..1."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(g, 80, 160).astype(np.float32)
    col = e.sum(axis=0)
    if col.sum() < 1:
        return 0.5
    return float((col * np.arange(len(col))).sum() / col.sum() / len(col))


def pick_frames(cand_dir: Path, k: int = 3, skip_ids: set[str] | None = None) -> list[Path]:
    """Sharp, contrasty, not blank. One per scene, best first. Text-card scenes are skipped (text over text)."""
    scored = []
    for p in sorted(cand_dir.glob("*.png")):
        if skip_ids and p.stem.split("-", 1)[-1] in skip_ids:
            continue
        img = np.asarray(Image.open(p).convert("RGB"))
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        sharp = cv2.Laplacian(g, cv2.CV_64F).var()
        sil = float(cv2.GaussianBlur(g, (0, 0), 8).std())  # figure/ground survives blur = good cover
        scored.append((sil >= 25, sil * 2 + float(g.std()) + min(sharp, 2000) / 40, p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    good = [p for ok, _, p in scored if ok] or [p for _, _, p in scored]
    return [good[i % len(good)] for i in range(k)] if good else []


def _font(path, size):
    return ImageFont.truetype(str(path), size)


def _wrap(words: list[str], font, maxw: int) -> list[list[str]]:
    lines, cur = [], []
    for w in words:
        if cur and font.getlength(" ".join(cur + [w])) > maxw:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _fit(words: list[str], font_path, maxw: int, maxh: int, start: int, minimum: int):
    size = start
    while size > minimum:
        f = _font(font_path, size)
        lines = _wrap(words, f, maxw)
        lh = int(size * 1.08)
        if len(lines) <= 3 and len(lines) * lh <= maxh and all(f.getlength(" ".join(ln)) <= maxw for ln in lines):
            return f, lines, size, lh
        size -= 6
    f = _font(font_path, minimum)
    return f, _wrap(words, f, maxw), minimum, int(minimum * 1.08)


def _draw_text(img: Image.Image, lines, font, lh: int, x: int, y: int, fg, accent_word: int, accent, stroke=0,
               stroke_col=None) -> list[int]:
    d = ImageDraw.Draw(img)
    k = 0
    x1 = x
    for li, ln in enumerate(lines):
        cx = x
        for w in ln:
            col = accent if k == accent_word else fg
            d.text((cx, y + li * lh), w, font=font, fill=col, stroke_width=stroke, stroke_fill=stroke_col)
            cx += font.getlength(w + " ")
            k += 1
        x1 = max(x1, int(cx - font.getlength(" ")))
    return [x, y, x1, y + len(lines) * lh]


def compose_cover(bg_img: np.ndarray, words: list[str], brand: B.Brand, variant: str, fmt: str, platforms: list[str]):
    W, H = SIZES[fmt]
    fg, bgc, ac = hex_to_rgb(brand.fg), hex_to_rgb(brand.bg), hex_to_rgb(brand.accent)
    sx = saliency_x(bg_img)
    text_left = sx >= 0.5  # text on the opposite side of the visual mass
    accent_word = max(range(len(words)), key=lambda i: len(words[i])) if words else 0
    if fmt == "16x9":
        area = (64, 64, W // 2 - 16, H - 64) if text_left else (W // 2 + 16, 64, W - 64, H - 64)
        start, minimum = 132, 84
    else:
        sz = safe_zone(platforms).rect
        area = (sz.x + 16, sz.y + 16, sz.x1 - 16, sz.y + int(sz.h * 0.55))
        start, minimum = 150, 96
    maxw, maxh = area[2] - area[0], area[3] - area[1]
    if variant == "minimal":
        canvas = Image.new("RGB", (W, H), bgc)
        if fmt == "16x9":
            win = (W // 2 + 32, 96, W - 96, H - 96) if text_left else (96, 96, W // 2 - 32, H - 96)
        else:
            sz = safe_zone(platforms).rect
            win = (sz.x + 32, sz.y + int(sz.h * 0.58), sz.x1 - 32, sz.y1 - 16)
        ww, wh = win[2] - win[0], win[3] - win[1]
        canvas.paste(Image.fromarray(_cover_fit(bg_img, ww, wh, sx, 0.4)), (win[0], win[1]))
        ImageDraw.Draw(canvas).rectangle(win, outline=fg, width=brand.line_width)
        f, lines, size, lh = _fit(words, brand.display.path, maxw, maxh, start, minimum)
        y = area[1] + (maxh - len(lines) * lh) // 2
        box = _draw_text(canvas, lines, f, lh, area[0], y, fg, accent_word, ac)
        text_col = fg
    elif variant == "punch":
        canvas = Image.fromarray(_cover_fit(bg_img, W, H, 1 - sx if fmt == "9x16" else 0.5, 0.45))
        f, lines, size, lh = _fit(words, brand.display.path, maxw - 48, maxh - 48, start, minimum)
        tw = max(int(f.getlength(" ".join(ln))) for ln in lines)
        th = len(lines) * lh
        px, py = area[0], area[1] + (maxh - th) // 2
        on_acc = brand.bg if contrast(brand.bg, brand.accent) >= contrast(brand.fg, brand.accent) else brand.fg
        ImageDraw.Draw(canvas).rectangle([px - 24, py - 16, px + tw + 24, py + th + 8], fill=ac)
        box = _draw_text(canvas, lines, f, lh, px, py, hex_to_rgb(on_acc), -1, ac)
        text_col = hex_to_rgb(on_acc)
    else:  # outline
        im = _cover_fit(bg_img, W, H, 0.5, 0.45).astype(np.float32)
        k = min(0.55, 70.0 / max(1.0, float(im.mean())))  # flat dim (no gradient) so white text reads on bright frames
        im = (im * k + np.array(bgc, np.float32) * (1 - k)).astype(np.uint8)
        canvas = Image.fromarray(im)
        f, lines, size, lh = _fit(words, brand.display.path, maxw, maxh, start, minimum)
        y = area[1] + (maxh - len(lines) * lh) // 2
        box = _draw_text(canvas, lines, f, lh, area[0], y, fg, accent_word, ac, stroke=max(4, size // 18),
                         stroke_col=(0, 0, 0))
        text_col = fg
    return canvas, {"box": box, "font_px": size, "text_color": rgb_to_hex(text_col), "text_left": text_left}


def check_cover(img: Image.Image, info: dict, words: list[str], fmt: str, platforms: list[str]) -> list[str]:
    errs = []
    W, H = img.size
    if not 3 <= len(words) <= 5:
        errs.append(f"{len(words)} words (need 3-5)")
    # readable at 320 px wide: cap height of the text >= 14 px after downscale
    cap_px = info["font_px"] * 0.7 * 320 / W
    if cap_px < 14:
        errs.append(f"text too small at 320 px ({cap_px:.0f}px cap height)")
    x0, y0, x1, y1 = info["box"]
    arr = np.asarray(img.convert("RGB"))
    reg = arr[max(0, y0):min(H, y1), max(0, x0):min(W, x1)].reshape(-1, 3)
    tc = np.array(hex_to_rgb(info["text_color"]))
    if len(reg):
        far = reg[np.abs(reg.astype(int) - tc).max(axis=1) > 60]
        if len(far):
            bgm = tuple(int(v) for v in np.median(far, axis=0))
            ratio = contrast(info["text_color"], bgm)
            if ratio < 4.5:
                errs.append(f"text contrast {ratio:.1f}:1 < 4.5:1")
    if fmt == "16x9":
        if x1 > W - 220 and y1 > H - 90:
            errs.append("text in the time-stamp corner")
    else:
        sz = safe_zone(platforms)
        from ..engine.layout import Rect

        if not sz.allows(Rect.from_xyxy(x0, y0, x1, y1), tol=8):
            errs.append("text outside the safe zone")
    if F.gradient_score(arr, min_run=10, block=16)["gradient"]:
        errs.append("gradient detected")
    sil = cv2.GaussianBlur(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY), (0, 0), 8)
    if sil.std() < 25:
        errs.append(f"weak silhouette (blurred grey std {sil.std():.0f})")
    return errs


def cover_dir(d: Path, image: str | None = None, text: str | None = None, generate: bool = True) -> dict:
    manifest = read_json(d / "manifest.json")
    plan = read_json(d / "plan.resolved.json")
    lang = manifest.get("language", "ru")
    brand = B.resolve(plan["brand"], None, lang)
    meta = read_json(d / "metadata.json") if (d / "metadata.json").exists() else {}
    words_s = text or meta.get("cover_text") or (plan.get("metadata") or {}).get("cover_text") or \
        next((s.get("on_screen_text") for s in plan["scenes"] if s.get("on_screen_text")), "") or manifest["name"]
    words_s = words_s.upper() if brand.upper else words_s
    words = words_s.split()[:5]
    out = d / "cover"
    out.mkdir(exist_ok=True)
    prov = generator()
    sources: list[tuple[str, np.ndarray]] = []
    notes = []
    if image:
        sources = [("user", np.asarray(Image.open(image).convert("RGB")))] * 3
    else:
        if prov and generate:
            try:
                p = generate_image(prompt_text(manifest, plan, words_s, "en"), out / "generated.png", prov)
                sources.append((f"model:{prov}", np.asarray(Image.open(p).convert("RGB"))))
                notes.append(f"background generated by {prov}")
            except Exception as e:  # report and fall back to frames
                notes.append(f"image generator {prov} failed: {str(e)[:120]}")
                log.warning("image generation failed: %s", e)
        text_ids = {sc["id"] for sc in manifest["scenes"] if sc["type"] == "text"}
        frames = pick_frames(out / "candidates", skip_ids=text_ids)
        sources += [(f"frame:{p.stem}", np.asarray(Image.open(p).convert("RGB"))) for p in frames]
        if not sources:
            sources = [("first", F.frame_at(d / manifest["video"], 0))]
    (out / "prompt.md").write_text(prompt_text(manifest, plan, words_s, lang), encoding="utf-8")
    variants = []
    for i, v in enumerate(("punch", "minimal", "outline")):
        src_name, src = sources[i % len(sources)]
        for fmt in SIZES:
            img, info = compose_cover(src, words, brand, v, fmt, manifest["platforms"])
            errs = check_cover(img, info, words, fmt, manifest["platforms"])
            p = out / f"cover-{chr(65 + i)}-{v}-{fmt}.jpg"
            img.save(p, quality=92)
            small = img.resize((320, int(320 * img.height / img.width)))
            small.save(out / f"cover-{chr(65 + i)}-{v}-{fmt}-320.png")
            variants.append({"file": p.name, "variant": v, "format": fmt, "source": src_name, "errors": errs, **info})
    res = {"generator": prov, "generated": any(s[0].startswith("model") for s in sources), "words": words,
           "variants": variants, "prompt": "cover/prompt.md", "notes": notes,
           "errors": [f"{x['file']}: {e}" for x in variants for e in x["errors"]]}
    if not res["generated"] and not image:
        res["ask_user"] = ("Генератора картинок нет или он выключен: обложки сделаны из кадров ролика. "
                           "Если нужна картинка от нейросети, сгенерируй по cover/prompt.md и пришли файл." if lang == "ru" else
                           "No image generator: covers use frames from the video. For a model image, use cover/prompt.md and send the file.")
    write_json(out / "cover.json", res)
    return res
