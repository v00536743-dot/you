#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Свои звуки для роликов: щелчок, поп, свуш, удар и подложка. Синтез кодом, без чужих файлов.

    python3 tools/make_sfx.py                 SFX в viora-shorts/assets/audio/sfx/ (если их нет)
    python3 tools/make_sfx.py --force         пересобрать
    python3 tools/make_sfx.py --music OUT.wav подложка 32 с, 96 BPM, петля без шва
    python3 tools/make_sfx.py --selftest

Зачем: у звуков из brag и video-shotcraft не у всех файлов найден источник и лицензия,
в поставку их не кладём. Эти звуки сгенерированы детерминированно (одинаковый результат
на любой машине), лицензия та же, что у скилла (MIT). Только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import struct
import sys
import tempfile
import wave

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.join(os.path.dirname(HERE), "viora-shorts", "assets", "audio", "sfx")
RATE = 44100
VERSION = "1.0.0"


def write(path: str, samples, rate: int = RATE, peak_db: float = -3.0) -> None:
    top = max(1e-9, max(abs(s) for s in samples))
    gain = (10 ** (peak_db / 20)) / top
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s * gain)) * 32767)) for s in samples)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)


def click(rng: random.Random):
    n = int(RATE * 0.03)
    return [(rng.uniform(-1, 1) * 0.5 + math.sin(2 * math.pi * 2200 * i / RATE)) * math.exp(-i / (RATE * 0.004))
            for i in range(n)]


def pop(rng: random.Random):
    n = int(RATE * 0.09)
    out, phase = [], 0.0
    for i in range(n):
        f = 900 - 600 * i / n
        phase += 2 * math.pi * f / RATE
        out.append(math.sin(phase) * math.exp(-i / (RATE * 0.025)))
    return out


def whoosh(rng: random.Random):
    n = int(RATE * 0.45)
    out, low = [], 0.0
    for i in range(n):
        x = i / n
        cutoff = 0.02 + 0.25 * math.sin(math.pi * x)
        low += cutoff * (rng.uniform(-1, 1) - low)
        out.append(low * math.sin(math.pi * x) ** 2)
    return out


def hit(rng: random.Random):
    n = int(RATE * 0.6)
    out, phase = [], 0.0
    for i in range(n):
        f = 58 - 18 * i / n
        phase += 2 * math.pi * f / RATE
        body = math.sin(phase) * math.exp(-i / (RATE * 0.18))
        snap = rng.uniform(-1, 1) * math.exp(-i / (RATE * 0.01)) * 0.6
        out.append(body + snap)
    return out


SOUNDS = {"click": click, "pop": pop, "whoosh": whoosh, "hit": hit}


def make_sfx(folder: str = SFX_DIR, force: bool = False) -> list:
    made = []
    for name, fn in SOUNDS.items():
        path = os.path.join(folder, "%s.wav" % name)
        if force or not os.path.exists(path):
            write(path, fn(random.Random(name)))
            made.append(path)
    return made


def music(path: str, seconds: float = 32.0, bpm: int = 96, rate: int = 22050) -> str:
    """Тихая подложка: мягкая бочка на долю, тихий хэт на слабую, ля-минорный пэд. Петля ровно в такт."""
    rng = random.Random("bed")
    beat = 60.0 / bpm
    beats = max(4, int(round(seconds / beat / 4)) * 4)
    n = int(beats * beat * rate)
    chord = (220.0, 261.63, 329.63)
    out = []
    for i in range(n):
        t = i / rate
        pos = t % beat
        kick = math.sin(2 * math.pi * (40 + 30 * math.exp(-pos * 30)) * pos) * math.exp(-pos * 12) * 0.9
        off = (t + beat / 2) % beat
        hat = rng.uniform(-1, 1) * math.exp(-off * 90) * 0.12
        lfo = 0.6 + 0.4 * math.sin(2 * math.pi * t / (beat * 8))
        pad = sum(math.sin(2 * math.pi * f * t) for f in chord) / 3 * 0.25 * lfo
        out.append(kick + hat + pad)
    write(path, out, rate, peak_db=-6.0)
    return path


def selftest() -> int:
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        made = make_sfx(tmp, force=True)
        checks.append(("четыре звука собраны", len(made) == 4))
        for path in made:
            with wave.open(path) as handle:
                ok = handle.getnchannels() == 1 and handle.getframerate() == RATE and handle.getnframes() > 100
            checks.append(("%s читается" % os.path.basename(path), ok))
        first = open(made[0], "rb").read()
        make_sfx(tmp, force=True)
        checks.append(("синтез детерминированный", open(made[0], "rb").read() == first))
        bed = music(os.path.join(tmp, "bed.wav"), seconds=4)
        with wave.open(bed) as handle:
            frames = handle.getnframes()
        checks.append(("подложка ровно в такт", frames == int(8 * 60 / 96 * 22050)))
    failed = 0
    for name, ok in checks:
        print("%s %s" % ("PASS" if ok else "FAIL", name))
        failed += 0 if ok else 1
    print("Итого: %d проверок звуков, провалилось %d" % (len(checks), failed))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Свои звуки для роликов VIORA")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--music")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.music:
        print("подложка: %s" % music(args.music))
        return 0
    made = make_sfx(force=args.force)
    print("собрано: %s" % (", ".join(os.path.basename(p) for p in made) if made else "всё уже на месте"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
