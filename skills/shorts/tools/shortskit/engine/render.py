"""plan.json -> finished vertical video + captions + manifest (what was drawn where and when, used by QA)."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .. import plan as P
from ..config import H, W
from ..util import ShortsError, ease, log, write_json
from . import audio as A
from . import brand as B
from . import captions as C
from . import graphics as G
from . import layout as L
from . import tts as T
from .clips import read_frames, video_info

PAD = 0.35  # silence after each voice line
FLASH_IN, FLASH_OUT = 0.25, 0.18


@dataclass
class SceneT:
    data: dict
    idx: int
    length: float = 0.0
    start: float = 0.0
    speech: T.Speech | None = None
    words: list[dict] = field(default_factory=list)  # relative to scene start
    clip: Path | None = None
    audio: Path | None = None
    clicks: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str = ""

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def type(self) -> str:
        return self.data["source"]["type"]


@dataclass
class Overlay:
    sprite: G.Sprite
    t0: float
    t1: float
    instant_in: bool = False
    arr: np.ndarray | None = None

    def alpha_scale(self, t: float) -> tuple[float, float]:
        if t < self.t0 or t >= self.t1:
            return 0.0, 1.0
        if not self.instant_in and t < self.t0 + FLASH_IN:
            k = ease((t - self.t0) / FLASH_IN)
            return k, 0.6 + 0.4 * k
        if t > self.t1 - FLASH_OUT:
            k = (self.t1 - t) / FLASH_OUT
            return max(0.0, k), 0.92 + 0.08 * k
        return 1.0, 1.0


def with_utm(url: str, name: str, platform: str) -> str:
    if not url.startswith(("http://", "https://")) or "t.me/" in url:
        return url
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(u.query)
    q += [("utm_source", platform), ("utm_medium", "short"), ("utm_campaign", name)]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), u.fragment))


def short_link(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").rstrip("/")


# ---------------------------------------------------------------- stage 1: voice and lengths

def voice_and_lengths(scenes: list[SceneT], plan: dict, lang: str) -> None:
    v = plan["audio"].get("voice", {})
    for s in scenes:
        say = s.data.get("say", "").strip()
        if say:
            s.speech = T.synth(say, lang=lang, engine=v.get("engine", "auto"), voice=v.get("voice"),
                               speed=float(v.get("speed", 1.0)))
            s.words = [dict(w) for w in s.speech.words]
            s.length = max(s.speech.duration + PAD, float(s.data.get("duration", 0)))
            if s.speech.estimated:
                s.notes.append(f"word timings estimated ({s.speech.engine})")
        elif s.data.get("duration"):
            s.length = float(s.data["duration"])
        elif s.type in ("video", "film"):
            src = s.data["source"]
            if src.get("out") is None:
                raise ShortsError(f"scene {s.id}: video/film without say needs duration or source.out")
            from .clips import SpeedMap

            s.length = SpeedMap(s.data.get("speed")).out_at(float(src["out"]) - float(src.get("in", 0)))
        else:
            raise ShortsError(f"scene {s.id}: no say and no duration")
        if s.data.get("transcript") and not say:
            s.words = [{"w": w["w"], "s": float(w["s"]), "e": float(w["e"])} for w in s.data["transcript"]]
        s.length = max(1.0, s.length)


def assign_starts(scenes: list[SceneT]) -> float:
    t = 0.0
    for s in scenes:
        if s.skipped:
            continue
        s.start = t
        t += s.length
    return t


# ---------------------------------------------------------------- stage 2: capture

async def _browser_jobs(jobs, top_job):
    from playwright.async_api import async_playwright

    from ..adapters import html as HT
    from ..adapters import site as SI

    async with async_playwright() as pw:
        browser = await SI.launch(pw)
        try:
            for fn in jobs:
                await fn(browser, SI, HT)
            if top_job:
                await top_job(browser, HT)
        finally:
            await browser.close()


def capture_all(scenes: list[SceneT], plan: dict, plan_dir: Path, lay: L.Layout, brand: B.Brand, fps: int,
                work: Path, lang: str, total_hint: float) -> dict:
    from ..adapters import media as ME
    from ..adapters import text_images as TI

    cw, ch = lay.center.w, lay.center.h
    jobs = []
    for s in scenes:
        t = s.type
        if t == "site":
            async def job(browser, SI, HT, s=s):
                cap = await SI.capture(browser, s.data, cw, ch, fps, s.length, work, lang, brand.accent)
                s.clip, s.clicks, s.notes, s.skipped = cap.clip, cap.clicks, s.notes + cap.notes, cap.skipped
            jobs.append(job)
        elif t == "html":
            path = P.resolve_ref(s.data["source"]["ref"], plan_dir)
            if not path:
                raise ShortsError(f"html file not found: {s.data['source']['ref']}")

            async def job(browser, SI, HT, s=s, path=path):
                cap = await HT.capture(browser, s.data, path, cw, ch, fps, s.length, work, lang, brand.accent)
                s.clip, s.clicks, s.notes = cap.clip, cap.clicks, s.notes + cap.notes
            jobs.append(job)
        elif t in ("video", "film"):
            cap = ME.capture(s.data, cw, ch, fps, s.length, work, plan_dir)
            s.clip, s.audio, s.notes = cap.clip, cap.audio, s.notes + cap.notes
        elif t == "images":
            cap = TI.images_capture(s.data, cw, ch, fps, s.length, work, plan_dir, brand.accent)
            s.clip, s.clicks = cap.clip, cap.clicks
        elif t == "text":
            y0 = 0
            if s.data.get("on_screen_text"):
                y0 = max(0, lay.label_box.y1 - lay.center.y + 16)
            y1 = ch
            if plan["captions"].get("enabled", True) and (s.words or s.data.get("say")):
                y1 = min(ch, lay.caption_band.y - lay.center.y - 16)
            cap = TI.text_capture(s.data, cw, ch, fps, s.length, work, plan_dir, brand, s.words, free=(y0, y1))
            s.clip, s.notes = cap.clip, s.notes + cap.notes
    top_info: dict = {"kind": "none"}
    top_job = None
    top = (plan["layout"].get("top") or {}) if lay.top else {}
    if lay.top:
        src = top.get("source", "")
        if src.startswith("html:"):
            path = P.resolve_ref(src[5:], plan_dir)
            if not path:
                raise ShortsError(f"top html not found: {src}")
            top_info = {"kind": "html", "path": str(work / "top.mp4"), "src": src}

            async def top_job(browser, HT, path=path):
                total = sum(s.length for s in scenes if not s.skipped)
                await HT.render_deterministic(browser, path.resolve().as_uri(), lay.top.w, lay.top.h, fps, total + 0.5,
                                              work / "top.mp4")
        elif src.startswith("color:"):
            top_info = {"kind": "color", "color": src[6:]}
        elif src:
            p = P.resolve_ref(src, plan_dir)
            if not p:
                raise ShortsError(f"top video not found: {src}")
            top_info = {"kind": "video", "path": str(p), "start": float(top.get("start", 0))}
    if jobs or top_job:
        asyncio.run(_browser_jobs(jobs, top_job))
    return top_info


# ---------------------------------------------------------------- stage 3: compose

def _blend(canvas: np.ndarray, sprite: np.ndarray, x: int, y: int, alpha: float) -> None:
    h, w = sprite.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.shape[1], x + w), min(canvas.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sp = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sp[..., 3:4].astype(np.float32) / 255.0 * alpha
    region = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = (region * (1 - a) + sp[..., :3].astype(np.float32) * a).astype(np.uint8)


def _top_frames(top_info: dict, lay: L.Layout, total: float, fps: int):
    n = int(round(total * fps)) + 2
    if not lay.top:
        return None
    if top_info["kind"] == "color":
        from ..util import hex_to_rgb

        frame = np.zeros((lay.top.h, lay.top.w, 3), np.uint8)
        frame[:] = hex_to_rgb(top_info["color"])
        return (frame for _ in range(n))
    if top_info["kind"] in ("video", "html"):
        return read_frames(top_info["path"], lay.top.w, lay.top.h, start=top_info.get("start", 0.0), fps=fps,
                           loop=top_info["kind"] == "video")
    return None


def _center_frames(scenes: list[SceneT], lay: L.Layout):
    for s in scenes:
        if s.skipped:
            continue
        info = video_info(s.clip)
        if (info["w"], info["h"]) != (lay.center.w, lay.center.h):
            raise ShortsError(f"clip {s.clip} has wrong size")
        yield from read_frames(s.clip, lay.center.w, lay.center.h)


def compose(out_mp4: Path, scenes: list[SceneT], lay: L.Layout, brand: B.Brand, overlays: list[Overlay],
            bottom_img: Image.Image | None, top_info: dict, total: float, fps: int, ass_path: Path | None,
            audio_wav: Path, fx: dict, loop: bool, cand_dir: Path | None = None) -> dict:
    from ..util import hex_to_rgb

    n = int(round(total * fps))
    bg = np.array(hex_to_rgb(brand.bg), np.uint8)
    bottom_arr = np.asarray(bottom_img.convert("RGB")) if bottom_img is not None else None
    for o in overlays:
        o.arr = np.asarray(o.sprite.img.convert("RGBA"))
    vf = []
    if ass_path:
        fonts_dir = str(brand.display.path.parent).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        vf.append(f"ass={ass_path.name}:fontsdir='{fonts_dir}'")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-i", str(audio_wav)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{n / fps:.3f}",
            "-movflags", "+faststart", out_mp4.name]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(out_mp4.parent))
    center_it = _center_frames(scenes, lay)
    top_it = _top_frames(top_info, lay, total, fps)
    punches = sorted(fx.get("punch") or [])
    flashes = sorted(fx.get("flash") or [])
    first = None
    last_c = None
    last_top = None
    loop_n = int(0.3 * fps) if loop else 0
    t_start = time.time()
    # clean centre frames (no captions, no overlays) for covers: middle of every scene
    cand = {}
    if cand_dir is not None:
        cand_dir.mkdir(parents=True, exist_ok=True)
        for s in scenes:
            if not s.skipped:
                cand[int((s.start + s.length * 0.55) * fps)] = s.id
    try:
        for k in range(n):
            t = k / fps
            canvas = np.empty((H, W, 3), np.uint8)
            canvas[:] = bg
            if lay.top is not None and top_it is not None:
                fr = next(top_it, None)
                last_top = fr if fr is not None else last_top
                if last_top is not None:
                    canvas[lay.top.y:lay.top.y1, :] = last_top
            c = next(center_it, None)
            last_c = c if c is not None else last_c
            if last_c is not None:
                cf = last_c
                p = [t - x for x in punches if 0 <= t - x < 0.3]
                if p:
                    z = 1 + 0.07 * (1 - ease(p[-1] / 0.3))
                    hh, ww = cf.shape[:2]
                    m = np.float32([[z, 0, -(z - 1) * ww / 2], [0, z, -(z - 1) * hh / 2]])
                    cf = cv2.warpAffine(cf, m, (ww, hh))
                canvas[lay.center.y:lay.center.y1, :] = cf
                if k in cand:
                    Image.fromarray(last_c).save(cand_dir / f"{k / fps:06.2f}-{cand[k]}.png")
            if bottom_arr is not None and lay.bottom is not None:
                canvas[lay.bottom.y:lay.bottom.y1, :] = bottom_arr
            cta_on = any(o.sprite.kind.startswith("cta") and o.t0 <= t < o.t1 for o in overlays)
            for o in overlays:
                if o.sprite.kind == "label" and cta_on:
                    continue
                a, s = o.alpha_scale(t)
                if a <= 0.01:
                    continue
                spr = o.arr
                bx = o.sprite.box
                if abs(s - 1) > 1e-3:
                    nw, nh = max(1, int(spr.shape[1] * s)), max(1, int(spr.shape[0] * s))
                    spr = cv2.resize(spr, (nw, nh), interpolation=cv2.INTER_LINEAR)
                    x = int(bx.x + (bx.w - nw) / 2)
                    y = int(bx.y + (bx.h - nh) / 2)
                else:
                    x, y = bx.x, bx.y
                _blend(canvas, spr, x, y, a)
            if any(0 <= t - x < 2 / fps for x in flashes):
                canvas = cv2.addWeighted(canvas, 0.6, np.full_like(canvas, 255), 0.4, 0)
            if k == 0:
                first = canvas.copy()
            if loop_n and k >= n - loop_n and first is not None:
                a = ease((k - (n - loop_n)) / loop_n)
                canvas = cv2.addWeighted(canvas, 1 - a, first, a, 0)
            assert proc.stdin
            proc.stdin.write(canvas.tobytes())
    finally:
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise ShortsError("final ffmpeg encode failed")
    return {"frames": n, "seconds": round(time.time() - t_start, 1)}


# ---------------------------------------------------------------- main entry

def render(plan_path: Path | str, out_dir: Path | str, force: bool = False, keep_work: bool = False) -> dict:
    raw, plan_dir = P.load(plan_path)
    issues = P.check(raw, plan_dir)
    errs = P.errors(issues)
    if errs and not force:
        raise ShortsError("plan has errors:\n" + "\n".join(str(i) for i in errs))
    plan = P.with_defaults(raw)
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    (out / "graphics").mkdir(exist_ok=True)
    lang = P.lang2(plan)
    fps = int(plan["meta"].get("fps", 30))
    platforms = plan["meta"]["platforms"]
    lay = L.compute(plan["layout"], platforms)
    brand = B.resolve(plan["brand"], plan_dir, lang)
    scenes = [SceneT(s, i) for i, s in enumerate(plan["scenes"])]
    t0 = time.time()
    voice_and_lengths(scenes, plan, lang)
    total = assign_starts(scenes)
    top_info = capture_all(scenes, plan, plan_dir, lay, brand, fps, work, lang, total)
    if all(s.skipped for s in scenes):
        raise ShortsError("every scene was skipped: " + "; ".join(s.skipped for s in scenes))
    total = assign_starts(scenes)
    live = [s for s in scenes if not s.skipped]

    # captions
    words: list[dict] = []
    for s in live:
        for w in s.words:
            words.append({"w": w["w"], "s": round(s.start + w["s"], 3), "e": round(s.start + min(w["e"], s.length), 3),
                          "scene": s.id})
    shown = C.apply_subs(words, plan["captions"].get("subs", {}))
    chunks: list[C.Chunk] = []
    ass_path = None
    if plan["captions"].get("enabled", True) and shown:
        chunks = C.build(shown, brand, lay, plan["captions"], lang)
        ass_path = out / "captions.ass"
        ass_path.write_text(C.to_ass(chunks, brand, plan["captions"], total), encoding="utf-8")
    if shown:
        (out / "captions.srt").write_text(C.to_srt(shown), encoding="utf-8")

    # overlays
    overlays: list[Overlay] = []
    for s in live:
        txt = (s.data.get("on_screen_text") or "").strip()
        if txt:
            spr = G.label(txt, brand, lay)
            if not lay.safe.allows(spr.box):
                s.notes.append(f"on_screen_text '{txt}' is too wide at {spr.min_font}px: shorten it (QA will fail)")
            overlays.append(Overlay(spr, s.start, s.start + s.length, instant_in=s.start == 0))
    bottom = plan["layout"].get("bottom") or {}
    name = plan["meta"]["name"]
    utm = bool(plan.get("metadata", {}).get("utm"))
    events: list[dict] = []
    for c in plan["layout"].get("cta_in_center", []):
        dur = float(c.get("duration", 2.5))
        t_c = float(c["t"])
        if t_c >= total:
            t_c = max(0.0, total - dur)
        if t_c + dur > total:
            t_c = max(0.0, total - dur)
        kind = c["kind"]
        if kind == "qr":
            url = with_utm(c["url"], name, platforms[0]) if utm else c["url"]
            spr = G.cta_qr(url, c.get("text") or short_link(c["url"]), brand, lay, c.get("y"))
        elif kind == "handle":
            link = c.get("url") or (bottom.get("links") or [""])[0]
            spr = G.cta_handle(c.get("text") or bottom.get("handle", ""), short_link(link) if link else "", brand, lay, c.get("y"))
        else:
            spr = G.cta_text(c.get("text", ""), brand, lay, c.get("y"))
        overlays.append(Overlay(spr, t_c, t_c + dur))
        events.append({"t": t_c, "kind": f"cta_{kind}"})
    bottom_img = None
    if lay.bottom is not None:
        logo = P.resolve_ref(bottom["logo"], plan_dir) if bottom.get("logo") else None
        bottom_img = G.bottom_panel(lay.bottom, brand, bottom.get("handle", ""), bottom.get("links", []),
                                    bottom.get("tagline", ""), logo)
        bottom_img.save(out / "graphics" / "bottom.png")
    for i, o in enumerate(overlays):
        o.sprite.img.save(out / "graphics" / f"{i:02d}-{o.sprite.kind}.png")

    # audio
    sfx: list[tuple[float, str]] = []
    for s in live:
        for e in s.data.get("sfx", []):
            sfx.append((s.start + float(e["t"]), e["name"]))
        if plan["audio"].get("sfx_auto", True):
            if s.start > 0:
                sfx.append((max(0.0, s.start - 0.12), "whoosh"))
            sfx += [(s.start + c, "click") for c in s.clicks]
    if plan["audio"].get("sfx_auto", True):
        sfx += [(o.t0, "pop") for o in overlays if o.sprite.kind.startswith("cta")]
    music = plan["audio"].get("music") or {}
    music_path = None
    if music.get("source") and music["source"] != "none":
        msrc = music["source"]
        if msrc.startswith(("http://", "https://")):
            from ..adapters.media import download_section

            music_path = download_section(msrc, audio_only=True)
        else:
            music_path = P.resolve_ref(msrc, plan_dir)
            if not music_path:
                raise ShortsError(f"music not found: {msrc}")
    voice_parts = [(s.start, s.speech.wav) for s in live if s.speech]
    src_parts = [(s.start, s.audio) for s in live if s.audio]
    audio_wav = work / "mix.wav"
    audio_rep = A.mix(total, voice_parts, src_parts, words, music, music_path, sfx, audio_wav,
                      float(plan["audio"].get("target_lufs", -14)))

    # compose
    out_mp4 = out / f"{name}.mp4"
    comp = compose(out_mp4, scenes, lay, brand, overlays, bottom_img, top_info, total, fps, ass_path, audio_wav,
                   plan.get("fx", {}), bool(plan["meta"].get("loop", True)), out / "cover" / "candidates")

    for s in live:
        events.append({"t": s.start, "kind": "scene", "id": s.id})
        events += [{"t": s.start + c, "kind": "click"} for c in s.clicks]
    events += [{"t": c.start, "kind": "caption"} for c in chunks]
    events += [{"t": o.t0, "kind": "label"} for o in overlays if o.sprite.kind == "label"]
    events += [{"t": float(x), "kind": "punch"} for x in plan.get("fx", {}).get("punch", [])]
    events.sort(key=lambda e: e["t"])
    manifest = {
        "engine": "shorts", "version": (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip(),
        "name": name, "video": out_mp4.name, "fps": fps, "duration": round(comp["frames"] / fps, 3),
        "language": lang, "platforms": platforms, "duration_target": plan["meta"].get("duration_target"),
        "loop": bool(plan["meta"].get("loop", True)), "layout": lay.to_dict(), "brand": brand.to_dict(),
        "top": top_info, "bottom": {"handle": bottom.get("handle"), "links": bottom.get("links", [])} if lay.bottom else None,
        "scenes": [{"id": s.id, "type": s.type, "start": round(s.start, 3), "length": round(s.length, 3),
                    "skipped": s.skipped, "notes": s.notes, "say": s.data.get("say", ""),
                    "on_screen_text": s.data.get("on_screen_text", "")} for s in scenes],
        "overlays": [dict(o.sprite.to_dict(), t0=round(o.t0, 3), t1=round(o.t1, 3)) for o in overlays],
        "captions": {"enabled": bool(chunks), "chunks": [{"text": c.text, "start": c.start, "end": c.end, "box": c.box,
                                                          "size": c.size, "lines": c.lines, "overflow": c.overflow,
                                                          "words": c.words} for c in chunks],
                     "words_spoken": words, "fill": brand.caption_fill, "accent": brand.caption_accent,
                     "outline": brand.caption_outline, "highlight": plan["captions"].get("highlight", "accent")},
        "events": events, "sfx": [{"t": round(t, 3), "name": n} for t, n in sorted(sfx)], "audio": audio_rep,
        "fx": plan.get("fx", {}), "effects": brand.effects, "issues": [str(i) for i in issues],
        "render_seconds": round(time.time() - t0, 1), "forced": bool(errs and force),
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "plan.resolved.json", plan)
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    log.info("rendered %s (%.1fs video) in %.0fs", out_mp4, total, time.time() - t0)
    return manifest
