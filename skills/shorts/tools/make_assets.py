"""Generate the skill's own assets (CC0, made by code): music bed and the top-panel game loop.

python3 tools/make_assets.py            # writes assets/audio/bed.mp3 and assets/footage/own-game-loop.mp4
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shortskit.config import asset  # noqa: E402
from shortskit.engine.audio import SR, _write_wav  # noqa: E402
from shortskit.util import run  # noqa: E402


def music_bed(seconds: float = 32.0, bpm: float = 112.0, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    beat = 60.0 / bpm
    out = np.zeros(n)
    # kick on every beat
    kick_n = int(0.25 * SR)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * np.cumsum(120 * np.exp(-kt * 30) + 42) / SR) * np.exp(-kt * 12)
    hat_n = int(0.05 * SR)
    hat = rng.standard_normal(hat_n) * np.exp(-np.arange(hat_n) / SR * 90)
    hat = np.diff(hat, prepend=0)
    roots = [45, 45, 41, 43]  # A, A, F, G (midi-ish offsets for bass)
    i = 0
    tb = 0.0
    while tb < seconds:
        s = int(tb * SR)
        out[s:s + kick_n] += kick[: max(0, min(kick_n, n - s))] * 0.9
        h = int((tb + beat / 2) * SR)
        if h < n:
            out[h:h + hat_n] += hat[: max(0, min(hat_n, n - h))] * 0.25
        bar = int(tb / (beat * 4)) % 4
        f = 440 * 2 ** ((roots[bar] - 69 + 12) / 12) / 2
        bn = int(beat * 0.9 * SR)
        bt = np.arange(min(bn, n - s)) / SR
        out[s:s + len(bt)] += 0.28 * np.sign(np.sin(2 * np.pi * f * bt)) * np.exp(-bt * 3.5)
        i += 1
        tb += beat
    # soft chord pad per bar
    for b in range(int(seconds / (beat * 4)) + 1):
        s = int(b * beat * 4 * SR)
        e = min(n, int((b + 1) * beat * 4 * SR))
        if s >= n:
            break
        pt = np.arange(e - s) / SR
        root = roots[b % 4] + 12
        pad = sum(np.sin(2 * np.pi * 440 * 2 ** ((root + iv - 69) / 12) * pt) for iv in (0, 3, 7))
        env = np.minimum(1, pt / 0.4) * np.minimum(1, (pt[-1] - pt) / 0.4 + 0.05)
        out[s:e] += 0.06 * pad * env
    # simple one-pole low-pass for warmth
    y = np.zeros_like(out)
    acc = 0.0
    a = 0.35
    for k in range(n):
        acc += a * (out[k] - acc)
        y[k] = acc
    y /= np.max(np.abs(y)) + 1e-9
    return np.stack([y, y], axis=1).astype(np.float32) * 0.8


async def game_loop(out: Path, seconds: float = 10.0, fps: int = 30) -> None:
    from playwright.async_api import async_playwright

    from shortskit.adapters.html import render_deterministic
    from shortskit.adapters.site import launch

    async with async_playwright() as pw:
        b = await launch(pw)
        await render_deterministic(b, asset("footage/game-loop.html").resolve().as_uri(), 1080, 384, fps, seconds, out)
        await b.close()


def main() -> None:
    wav = asset("audio/bed.wav")
    asset("audio").mkdir(parents=True, exist_ok=True)
    _write_wav(wav, music_bed())
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "96k", asset("audio/bed.mp3")])
    wav.unlink()
    tmp = asset("footage/own-game-loop.tmp.mp4")
    asyncio.run(game_loop(tmp))
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-c:v", "libx264", "-crf", "30", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-an", asset("footage/own-game-loop.mp4")])
    tmp.unlink()
    print("ok:", asset("audio/bed.mp3"), asset("footage/own-game-loop.mp4"))


if __name__ == "__main__":
    main()
