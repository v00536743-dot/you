"""Adapters `text` and `images`: frames drawn in Python (no browser).

text:   kinetic typography in brand fonts, words appear in sync with the voice; *word* = accent.
        Optional `images` behind the text (user screenshots or project frames), darkened.
images: user screenshots in motion (slow zoom and pan towards `focus`), optional fake cursor clicks
        (`points`: [[x, y, t], ...] in 0..1 image coords and scene seconds).
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..engine.clips import ClipWriter, cover_resize
from ..plan import resolve_ref
from ..util import ShortsError, ease, hex_to_rgb, snap8
from .site import Capture


def _load(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ShortsError(f"cannot read image {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _ken_burns(img: np.ndarray, w: int, h: int, k: float, focus=(0.5, 0.5), zoom=(1.0, 1.12)) -> np.ndarray:
    base = cover_resize(img, int(w * zoom[1]) + 2, int(h * zoom[1]) + 2, focus[0], focus[1])
    z = zoom[0] + (zoom[1] - zoom[0]) * ease(k)
    cw, ch = int(w * zoom[1] / z), int(h * zoom[1] / z)
    bh, bw = base.shape[:2]
    x0 = int((bw - cw) * focus[0])
    y0 = int((bh - ch) * focus[1])
    crop = base[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA)


def images_capture(scene: dict, w: int, h: int, fps: int, out_len: float, work: Path, plan_dir: Path | None,
                   accent: str) -> Capture:
    src = scene["source"]
    refs = list(src.get("images") or ([src["ref"]] if src.get("ref") else []))
    if not refs:
        raise ShortsError(f"scene {scene['id']}: images adapter needs images or ref")
    paths = []
    for r in refs:
        p = resolve_ref(r, plan_dir)
        if not p:
            raise ShortsError(f"image not found: {r}")
        paths.append(p)
    imgs = [_load(p) for p in paths]
    focus = tuple(src.get("focus", (0.5, 0.4)))
    points = src.get("points") or []
    n = max(1, int(round(out_len * fps)))
    per = n / len(imgs)
    out = work / f"center-{scene['id']}.mp4"
    wr = ClipWriter(out, w, h, fps)
    clicks = []
    acc = hex_to_rgb(accent)
    for k in range(n):
        i = min(len(imgs) - 1, int(k / per))
        local = (k - i * per) / per
        frame = _ken_burns(imgs[i], w, h, local, focus).copy()
        t = k / fps
        for (px, py, pt) in points:
            dt = t - float(pt)
            if 0 <= dt < 0.5:
                r = int(28 + 40 * ease(dt / 0.5))
                a = 1 - dt / 0.5
                over = frame.copy()
                cv2.circle(over, (int(px * w), int(py * h)), r, acc, 4, cv2.LINE_AA)
                frame = cv2.addWeighted(over, a, frame, 1 - a, 0)
        wr.write(frame)
    wr.close()
    clicks = [float(p[2]) for p in points if float(p[2]) < out_len]
    return Capture(out, clicks)


def _tokens(text: str) -> list[tuple[str, bool]]:
    out = []
    for t in text.split():
        acc = t.startswith("*") and t.rstrip(".,!?:;").endswith("*")
        out.append((t.replace("*", ""), acc))
    return out


def text_capture(scene: dict, w: int, h: int, fps: int, out_len: float, work: Path, plan_dir: Path | None,
                 brand, words: list[dict]) -> Capture:
    src = scene["source"]
    text = src.get("ref") or scene.get("on_screen_text") or scene.get("say", "")
    toks = _tokens(text.upper() if brand.upper else text)
    if not toks:
        raise ShortsError(f"scene {scene['id']}: text adapter has no text")
    bg_imgs = [_load(p) for p in (resolve_ref(r, plan_dir) for r in src.get("images") or []) if p]
    margin = 72
    maxw = w - 2 * margin
    size = 168
    while size > 72:
        f = ImageFont.truetype(str(brand.display.path), size)
        lines, cur = [], []
        for tok, a in toks:
            trial = " ".join(x for x, _ in cur + [(tok, a)])
            if f.getlength(trial) > maxw and cur:
                lines.append(cur)
                cur = [(tok, a)]
            else:
                cur.append((tok, a))
        if cur:
            lines.append(cur)
        asc, desc = f.getmetrics()
        lh = int((asc + desc) * 1.02)
        if len(lines) * lh <= h * 0.62 and all(f.getlength(" ".join(x for x, _ in ln)) <= maxw for ln in lines):
            break
        size -= 8
    # word appearance times: voice words if they match, else spread over the first 60% of the scene
    flat = [t for ln in lines for t in ln]
    times = []
    if words and len(words) >= len(flat):
        step = len(words) / len(flat)
        times = [words[int(i * step)]["s"] for i in range(len(flat))]
    else:
        times = [i * (out_len * 0.6) / max(1, len(flat)) for i in range(len(flat))]
    bg = hex_to_rgb(brand.bg)
    fg = hex_to_rgb(brand.fg)
    ac = hex_to_rgb(brand.accent)
    block_h = len(lines) * lh
    y0 = snap8((h - block_h) / 2 - h * 0.06)
    out = work / f"center-{scene['id']}.mp4"
    wr = ClipWriter(out, w, h, fps)
    n = max(1, int(round(out_len * fps)))
    for k in range(n):
        t = k / fps
        if bg_imgs:
            base = _ken_burns(bg_imgs[min(len(bg_imgs) - 1, int(t / out_len * len(bg_imgs)))], w, h, t / out_len)
            base = (base.astype(np.float32) * 0.35 + np.array(bg, np.float32) * 0.65).astype(np.uint8)
            img = Image.fromarray(base)
        else:
            img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        idx = 0
        for li, ln in enumerate(lines):
            line_text = " ".join(x for x, _ in ln)
            x = margin
            y = y0 + li * lh
            for tok, a in ln:
                appear = times[idx]
                p = ease((t - appear) / 0.25) if t >= appear else 0.0
                idx += 1
                tw = f.getlength(tok + " ")
                if p > 0:
                    dy = snap8((1 - p) * 24)
                    col = ac if a else fg
                    colp = tuple(int(bg[c] + (col[c] - bg[c]) * p) for c in range(3))
                    d.text((x, y + dy), tok, font=f, fill=colp)
                x += tw
            del line_text
        # one line element that grows with the scene: shows progress, not decoration
        bar_w = int((w - 2 * margin) * ease(min(1.0, t / max(0.5, out_len))))
        d.rectangle([margin, y0 + block_h + 32, margin + bar_w, y0 + block_h + 32 + brand.line_width], fill=ac)
        wr.write(np.asarray(img))
    wr.close()
    return Capture(out, notes=[f"text card {len(lines)} lines at {size}px"])


def strip_marks(text: str) -> str:
    return re.sub(r"\*", "", text or "")
