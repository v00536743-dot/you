"""Adapter `html`: film a local HTML file (game, animation, three.js "film") with controlled speed.

Deterministic mode (default): time is virtual. Order of hooks:
  1. window.__seek(t)  - the page renders time t itself (best, exact);
  2. window.frame(dt)  - the page advances by dt (prototype games);
  3. otherwise a shim virtualises performance.now, Date, requestAnimationFrame, timers and Web Animations
     (CSS animations/transitions) so any page can be stepped frame by frame.
Realtime mode: screencast like the site adapter, then the speed map retimes it.
HTML pages make no sound in the video: voice, music and SFX come from the plan.
"""
from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np

from ..engine.clips import ClipWriter, SpeedMap, cover_resize
from ..util import ShortsError
from .site import Capture, capture as site_capture

VT_JS = """
(() => {
  if (window.__shortsVT) return;
  let now = 0; const start = 1767225600000; // fixed epoch -> same output every run
  const RealDate = Date;
  class VDate extends RealDate { constructor(...a) { if (a.length === 0) super(start + now); else super(...a); }
    static now() { return start + now; } }
  window.Date = VDate;
  performance.now = () => now;
  let seed = %SEED%; Math.random = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const rafs = new Map(); let rid = 1; const timers = new Map(); let tid = 1;
  window.requestAnimationFrame = cb => { const id = rid++; rafs.set(id, cb); return id; };
  window.cancelAnimationFrame = id => rafs.delete(id);
  window.setTimeout = (cb, ms = 0, ...a) => { const id = tid++; timers.set(id, {cb, at: now + Math.max(0, +ms || 0), a}); return id; };
  window.setInterval = (cb, ms = 0, ...a) => { const e = Math.max(1, +ms || 0); const id = tid++; timers.set(id, {cb, at: now + e, a, every: e}); return id; };
  window.clearTimeout = window.clearInterval = id => timers.delete(id);
  const born = new WeakMap();
  window.__shortsVT = {
    advanceTo(t) {
      for (let guard = 0; guard < 10000; guard++) {
        let best = null;
        for (const [id, x] of timers) if (x.at <= t && (!best || x.at < best[1].at)) best = [id, x];
        if (!best) break;
        const [id, x] = best; now = x.at;
        if (x.every) x.at += x.every; else timers.delete(id);
        try { typeof x.cb === 'function' ? x.cb(...x.a) : (0, eval)(x.cb); } catch (e) { console.error(e); }
      }
      now = t;
      const cbs = [...rafs.values()]; rafs.clear();
      for (const cb of cbs) { try { cb(now); } catch (e) { console.error(e); } }
      if (document.getAnimations) for (const an of document.getAnimations()) {
        if (!born.has(an)) born.set(an, now);
        try { an.pause(); an.currentTime = Math.max(0, now - born.get(an)); } catch (e) {}
      }
    }
  };
})();
"""


async def _hooks(page) -> str:
    return await page.evaluate("() => typeof window.__seek === 'function' ? 'seek' : (typeof window.frame === 'function' ? 'frame' : 'vt')")


async def render_deterministic(browser, url: str, w: int, h: int, fps: int, out_len: float, out: Path,
                               viewport: dict | None = None, speed: SpeedMap | None = None, seed: int = 7,
                               start: float = 0.0) -> str:
    speed = speed or SpeedMap(None)
    vp = viewport or {"width": w, "height": h}
    dpr = w / vp["width"] if viewport is None else 1.0
    ctx = await browser.new_context(viewport=vp, device_scale_factor=max(1.0, dpr))
    await ctx.add_init_script(VT_JS.replace("%SEED%", str(int(seed))))
    page = await ctx.new_page()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts && document.fonts.ready")
    hook = await _hooks(page)
    cdp = await ctx.new_cdp_session(page)
    wr = ClipWriter(out, w, h, fps)
    prev = start
    if hook == "frame" and start > 0:
        steps = int(start * 60)
        for _ in range(steps):
            await page.evaluate("dt => window.frame(dt)", 1 / 60)
    n = max(1, int(round(out_len * fps)))
    for k in range(n):
        t = start + speed.src_at(k / fps)
        if hook == "seek":
            await page.evaluate("t => window.__seek(t)", t)
        elif hook == "frame":
            dt = t - prev
            sub = max(1, int(np.ceil(dt * 60 - 1e-6)))  # physics in <= 1/60 s steps
            for _ in range(sub):
                await page.evaluate("dt => window.frame(dt)", dt / sub)
        else:
            await page.evaluate("t => window.__shortsVT.advanceTo(t)", t * 1000.0)
        prev = t
        shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92})
        img = cv2.imdecode(np.frombuffer(base64.b64decode(shot["data"]), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ShortsError("screenshot failed")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if img.shape[1] != w or img.shape[0] != h:
            img = cover_resize(img, w, h)
        wr.write(img)
    wr.close()
    await ctx.close()
    return hook


async def capture(browser, scene: dict, path: Path, w: int, h: int, fps: int, out_len: float, work: Path,
                  lang: str, accent: str) -> Capture:
    src = scene["source"]
    url = path.resolve().as_uri()
    if src.get("mode") == "realtime":
        return await site_capture(browser, scene, w, h, fps, out_len, work, lang, accent, file_url=url)
    vp = src.get("viewport")
    viewport = {"width": int(vp["w"]), "height": int(vp["h"])} if isinstance(vp, dict) else None
    out = work / f"center-{scene['id']}.mp4"
    hook = await render_deterministic(browser, url, w, h, fps, out_len, out, viewport, SpeedMap(scene.get("speed")),
                                      seed=int(src.get("seed", 7)), start=float(src.get("in", 0)))
    return Capture(out, notes=[f"html rendered deterministically via {hook}"])
