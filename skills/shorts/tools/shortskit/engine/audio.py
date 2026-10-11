"""Sound: synthesized SFX (our own code, CC0), voice/music/SFX mix, ducking, loudness to -14 LUFS / -1 dBTP."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from ..config import asset
from ..util import ShortsError, log, run

SR = 48000
SFX_GAIN_DB = -14.0


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / max(decay, 1e-4))


def synth_sfx(name: str, seed: int = 1) -> np.ndarray:
    """Small procedural library: click, whoosh, hit, pop, tick, riser, shutter."""
    rng = np.random.default_rng(seed)
    if name == "click":
        n = int(0.05 * SR)
        t = np.arange(n) / SR
        x = 0.6 * np.sin(2 * np.pi * 2300 * t) * _env(n, 0.0005, 0.006) + 0.4 * rng.standard_normal(n) * _env(n, 0.0002, 0.003)
    elif name == "tick":
        n = int(0.03 * SR)
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * 3200 * t) * _env(n, 0.0003, 0.004)
    elif name == "pop":
        n = int(0.12 * SR)
        t = np.arange(n) / SR
        f = 900 * np.exp(-t * 18) + 300
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.04)
    elif name == "whoosh":
        n = int(0.38 * SR)
        noise = rng.standard_normal(n)
        k = np.linspace(0, 1, n)
        out = np.zeros(n)
        y = 0.0
        for i in range(n):  # one-pole low-pass with a cutoff sweep
            a = 0.02 + 0.25 * np.sin(np.pi * k[i]) ** 2
            y += a * (noise[i] - y)
            out[i] = y
        x = out * np.sin(np.pi * k) ** 1.5 * 3
    elif name == "hit":
        n = int(0.5 * SR)
        t = np.arange(n) / SR
        f = 110 * np.exp(-t * 9) + 45
        x = 0.9 * np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.001, 0.16) + 0.35 * rng.standard_normal(n) * _env(n, 0.0005, 0.02)
    elif name == "riser":
        n = int(1.0 * SR)
        t = np.arange(n) / SR
        f = 200 + 1400 * t ** 2
        x = (0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * rng.standard_normal(n)) * (t / t[-1]) ** 2
    elif name == "shutter":
        a, b = synth_sfx("click", seed), synth_sfx("click", seed + 1)
        x = np.concatenate([a, np.zeros(int(0.04 * SR)), b * 0.8])
    else:
        lib = asset(f"audio/sfx/{name}.wav")
        if lib.exists():
            return load_audio(lib, mono=True)
        raise ShortsError(f"unknown sfx '{name}' (built-in: click, tick, pop, whoosh, hit, riser, shutter; or add assets/audio/sfx/{name}.wav)")
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    return x.astype(np.float32)


def load_audio(path: Path | str, mono: bool = False, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-f", "f32le", "-ac", "1" if mono else "2", "-ar", str(SR), "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise ShortsError(f"cannot decode audio {path}: {p.stderr.decode()[-300:]}")
    a = np.frombuffer(p.stdout, np.float32)
    return a if mono else a.reshape(-1, 2)


def lufs(x: np.ndarray) -> float:
    import pyloudnorm as pyln

    if x.ndim == 1:
        x = x[:, None]
    if len(x) < SR * 0.5 or np.max(np.abs(x)) < 1e-6:
        return -70.0
    return float(pyln.Meter(SR).integrated_loudness(x.astype(np.float64)))


def db(v: float) -> float:
    return 10 ** (v / 20)


def regions_envelope(n: int, regions: list[tuple[float, float]], depth_db: float, attack: float = 0.12,
                     release: float = 0.25) -> np.ndarray:
    """Gain curve: 1.0 outside regions, db(depth) inside, with linear ramps."""
    g = np.ones(n, np.float32)
    lo = db(depth_db)
    for s, e in regions:
        a0, a1 = int((s - attack) * SR), int(s * SR)
        r0, r1 = int(e * SR), int((e + release) * SR)
        a0c, r1c = max(0, a0), min(n, r1)
        if a1 > a0c:
            ramp = np.linspace(1, lo, max(1, a1 - a0))[a0c - a0:]
            g[a0c:a1] = np.minimum(g[a0c:a1], ramp[: a1 - a0c])
        g[max(0, a1):min(n, r0)] = lo
        if r1c > r0 >= 0:
            ramp = np.linspace(lo, 1, max(1, r1 - r0))[: r1c - r0]
            g[r0:r1c] = np.minimum(g[r0:r1c], ramp)
    return g


def speech_regions(words: list[dict], gap: float = 0.4) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for w in sorted(words, key=lambda x: x["s"]):
        if out and w["s"] - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], w["e"])
        else:
            out.append([w["s"], w["e"]])
    return [(a, b) for a, b in out]


def place(track: np.ndarray, clip: np.ndarray, t: float, gain: float = 1.0) -> None:
    i = int(t * SR)
    if i >= len(track) or i < 0:
        return
    if clip.ndim == 1 and track.ndim == 2:
        clip = np.repeat(clip[:, None], 2, axis=1)
    n = min(len(clip), len(track) - i)
    track[i:i + n] += clip[:n] * gain


def mix(total: float, voice_parts: list[tuple[float, Path]], src_parts: list[tuple[float, Path]], words: list[dict],
        music: dict | None, music_path: Path | None, sfx: list[tuple[float, str]], out_wav: Path,
        target_lufs: float = -14.0) -> dict:
    n = int(total * SR) + 1
    voice = np.zeros((n, 2), np.float32)
    for t, p in voice_parts:
        place(voice, load_audio(p, mono=True), t)
    src = np.zeros((n, 2), np.float32)
    for t, p in src_parts:
        place(src, load_audio(p), t)
    has_voice = np.max(np.abs(voice)) > 1e-4
    report: dict = {"voice": bool(has_voice)}
    mus = np.zeros((n, 2), np.float32)
    if music_path:
        m = load_audio(music_path, start=float((music or {}).get("start", 0)))
        if len(m) == 0:
            raise ShortsError(f"music file is empty: {music_path}")
        reps = int(np.ceil(n / len(m)))
        m = np.tile(m, (reps, 1))[:n]
        fade_in, fade_out = int(0.3 * SR), int(0.8 * SR)
        m[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
        m[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
        if has_voice or np.max(np.abs(src)) > 1e-4:
            ref = lufs(voice + src)
            ml = lufs(m)
            sep = float((music or {}).get("gain_db", -10.0))  # music this far under the voice during speech
            gain_db = ref - ml + sep
            duck = float((music or {}).get("duck_db", -10.0))
            lift = min(abs(duck), 6.0)  # between phrases music comes up a little
            regions = speech_regions(words) if words else [(0.0, total)]
            env = regions_envelope(n, regions, -lift)
            m = m * db(gain_db + lift) * env[:, None]
            report.update(music_gain_db=round(gain_db, 1), duck_db=-lift, separation_db=-sep)
        mus = m
    fx = np.zeros((n, 2), np.float32)
    for t, name in sfx:
        place(fx, synth_sfx(name, seed=int(t * 100) % 97 + 1), t, db(SFX_GAIN_DB))
    mixd = voice + src + mus + fx
    if has_voice and music_path:
        speech_mask = regions_envelope(n, speech_regions(words) if words else [], -60) < 0.5
        if speech_mask.any():
            report["voice_minus_music_db"] = round(lufs(voice[speech_mask]) - lufs(mus[speech_mask]), 1)
    raw = out_wav.with_suffix(".premaster.wav")
    _write_wav(raw, mixd)
    loudnorm(raw, out_wav, target_lufs)
    raw.unlink(missing_ok=True)
    return report


def _write_wav(path: Path, x: np.ndarray) -> None:
    x = np.clip(x, -4, 4).astype(np.float32)
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
                        "-c:a", "pcm_f32le", str(path)], input=x.tobytes(), capture_output=True)
    if p.returncode != 0:
        raise ShortsError(p.stderr.decode()[-300:])


def loudnorm(src: Path, dst: Path, target: float = -14.0, tp: float = -1.5) -> dict:
    """Two-pass EBU R128 loudnorm (linear when possible)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr.decode(errors="replace"))
    if not m:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", f"loudnorm=I={target}:TP={tp}:LRA=11", "-ar", SR, dst])
        return {}
    st = json.loads(m.group(0))
    if float(st["input_i"]) < -60:  # silence
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ar", SR, "-c:a", "pcm_s16le", dst])
        return st
    af = (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
          f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", af, "-ar", SR, "-c:a", "pcm_s16le", dst])
    log.debug("loudnorm: %s", st)
    return st


def measure(path: Path | str) -> dict:
    """Integrated loudness, true peak, sample peak (for QA)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true,astats=metadata=0",
                        "-f", "null", "-"], capture_output=True)
    err = p.stderr.decode(errors="replace")
    i = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    pk = re.findall(r"Peak level dB:\s+(-?[\d.]+|-inf)", err)
    clip = re.findall(r"Number of clipped samples:\s+(\d+)", err)  # not printed by every build

    def f(v: list[str]) -> float:
        if not v:
            return float("nan")
        return -99.0 if v[-1] == "-inf" else float(v[-1])

    return {"lufs": f(i), "true_peak": f(tp), "sample_peak": f(pk), "clipped": int(clip[-1]) if clip else None}


def beats(path: Path | str, start: float = 0.0, duration: float | None = None) -> dict:
    """Beat grid and strong beats (librosa). Strong = top 40% onset strength; downbeat phase picked by energy."""
    import librosa

    y, sr = librosa.load(str(path), sr=22050, mono=True, offset=start, duration=duration)
    if len(y) < sr:
        raise ShortsError("music too short for beat analysis")
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, bf = librosa.beat.beat_track(onset_envelope=onset, sr=sr, units="frames")
    bt = librosa.frames_to_time(bf, sr=sr)
    st = onset[np.clip(bf, 0, len(onset) - 1)] if len(bf) else np.array([])
    thr = np.quantile(st, 0.6) if len(st) else 0
    strong = [float(t) for t, s in zip(bt, st) if s >= thr]
    phase = int(np.argmax([st[i::4].sum() for i in range(4)])) if len(st) >= 8 else 0
    downs = [float(t) for t in bt[phase::4]]
    rms = librosa.feature.rms(y=y)[0]
    rt = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    tempo_v = float(np.atleast_1d(tempo)[0])
    return {"tempo": round(tempo_v, 2), "beats": [round(float(t), 3) for t in bt], "strong": [round(t, 3) for t in strong],
            "downbeats": [round(t, 3) for t in downs], "energy": {"t": [round(float(t), 2) for t in rt[::10]],
                                                                  "rms": [round(float(v), 4) for v in rms[::10]]},
            "duration": round(len(y) / sr, 2)}
