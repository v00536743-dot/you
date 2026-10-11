"""Text to speech with word timings, a fallback chain and a cache.

Chain for engine "auto": edge -> elevenlabs (if ELEVENLABS_API_KEY) -> openai (if OPENAI_API_KEY) -> piper (if installed).
Every result is cached by (engine, voice, speed, text); a cache hit needs no network (tests use this).
"silent" makes silence with estimated timings, for dry runs only.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import cache_dir
from ..util import ShortsError, log, media_duration, run

SR = 48000

VOICES = {
    "edge": {
        "ru-male-1": "ru-RU-DmitryNeural", "ru-female-1": "ru-RU-SvetlanaNeural",
        "en-male-1": "en-US-AndrewNeural", "en-female-1": "en-US-AvaNeural",
        "en-male-2": "en-US-BrianNeural", "en-female-2": "en-US-EmmaNeural",
        "uk-male-1": "uk-UA-OstapNeural", "de-male-1": "de-DE-ConradNeural", "es-male-1": "es-ES-AlvaroNeural",
    },
    "openai": {"ru-male-1": "onyx", "ru-female-1": "nova", "en-male-1": "onyx", "en-female-1": "nova"},
}
DEFAULT_VOICE = {"ru": "ru-male-1", "en": "en-male-1", "uk": "uk-male-1", "de": "de-male-1", "es": "es-male-1"}


@dataclass
class Speech:
    wav: Path
    duration: float
    words: list[dict]  # {"w", "s", "e"} seconds from start of this clip
    engine: str
    voice: str
    estimated: bool = False


def _key(engine: str, voice: str, speed: float, text: str) -> str:
    return hashlib.sha256(f"{engine}|{voice}|{speed:.3f}|{text}".encode()).hexdigest()[:24]


def _cache_get(key: str) -> Speech | None:
    d = cache_dir("tts")
    w, j = d / f"{key}.wav", d / f"{key}.json"
    if w.exists() and j.exists():
        m = json.loads(j.read_text(encoding="utf-8"))
        return Speech(w, m["duration"], m["words"], m["engine"], m["voice"], m.get("estimated", False))
    return None


def _cache_put(key: str, src_audio: Path, words: list[dict], engine: str, voice: str, estimated: bool) -> Speech:
    d = cache_dir("tts")
    w = d / f"{key}.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src_audio, "-ar", SR, "-ac", 1, "-c:a", "pcm_s16le", w])
    dur = media_duration(w)
    (d / f"{key}.json").write_text(json.dumps({"duration": dur, "words": words, "engine": engine, "voice": voice,
                                               "estimated": estimated}, ensure_ascii=False), encoding="utf-8")
    return Speech(w, dur, words, engine, voice, estimated)


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", text.strip()) if t]


def estimate_words(text: str, duration: float, lead: float = 0.05) -> list[dict]:
    """Spread words over the clip by vowel count (rough syllables). Marked as estimated."""
    toks = tokenize(text)
    weights = [max(1, len(re.findall(r"[aeiouyаеёиоуыэюяіїє]", t.lower()))) + 0.3 for t in toks]
    total = sum(weights) or 1
    span = max(0.1, duration - lead - 0.1)
    t, out = lead, []
    for tok, wt in zip(toks, weights):
        d = span * wt / total
        out.append({"w": tok, "s": round(t, 3), "e": round(t + d * 0.92, 3)})
        t += d
    return out


def _align_words_to_text(text: str, boundaries: list[tuple[str, float, float]]) -> list[dict]:
    """Map engine word boundaries back onto the original tokens (keeps punctuation for chunking)."""
    toks = tokenize(text)
    out, bi = [], 0
    for tok in toks:
        core = re.sub(r"[^\w]", "", tok.lower())
        if not core:  # pure punctuation token: glue to previous word
            if out:
                out[-1]["w"] += " " + tok
            continue
        match = None
        for j in range(bi, min(bi + 4, len(boundaries))):
            if re.sub(r"[^\w]", "", boundaries[j][0].lower()) in (core, core[: len(boundaries[j][0])]):
                match = j
                break
        if match is None and bi < len(boundaries):
            match = bi
        if match is None:
            s = out[-1]["e"] if out else 0.0
            out.append({"w": tok, "s": s, "e": s + 0.2})
            continue
        _, s, e = boundaries[match]
        out.append({"w": tok, "s": round(s, 3), "e": round(e, 3)})
        bi = match + 1
    return out


# ---------------------------------------------------------------- engines

async def _edge(text: str, voice: str, speed: float, out: Path) -> list[tuple[str, float, float]]:
    import edge_tts

    rate = f"{int(round((speed - 1) * 100)):+d}%"
    audio, bounds = bytearray(), []
    async for ch in edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary").stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            s = ch["offset"] / 1e7
            bounds.append((ch["text"], s, s + ch["duration"] / 1e7))
    if not audio:
        raise ShortsError("edge-tts returned no audio")
    out.write_bytes(bytes(audio))
    return bounds


def _edge_sync(text: str, voice: str, speed: float, out: Path, attempts: int = 6) -> list[tuple[str, float, float]]:
    import time

    delay = 2.0
    for i in range(attempts):
        try:
            return asyncio.run(_edge(text, voice, speed, out))
        except Exception as e:  # service sometimes answers with nothing
            if i == attempts - 1:
                raise ShortsError(f"edge-tts failed {attempts} times: {e}") from e
            log.warning("edge-tts: %s, retry in %.0fs", e, delay)
            time.sleep(delay)
            delay = min(delay * 1.7, 15)
    raise AssertionError


def _http_json(url: str, payload: dict, headers: dict, timeout: float = 90) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https endpoints)
        return r.read()


def _elevenlabs(text: str, voice: str, speed: float, out: Path) -> list[tuple[str, float, float]]:
    """ElevenLabs 'with-timestamps' gives character alignment, turned into word boundaries. Not verified without a key."""
    key = os.environ["ELEVENLABS_API_KEY"]
    vid = voice if re.fullmatch(r"[A-Za-z0-9]{16,}", voice) else os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not vid:
        raise ShortsError("set ELEVENLABS_VOICE_ID or give a voice id")
    raw = _http_json(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps",
                     {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"speed": speed}},
                     {"xi-api-key": key})
    data = json.loads(raw)
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or {}
    chars, st, en = al.get("characters", []), al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
    bounds, cur, s0 = [], "", None
    for c, s, e in zip(chars, st, en):
        if c.isspace():
            if cur:
                bounds.append((cur, s0, prev_e))
            cur, s0 = "", None
            continue
        if s0 is None:
            s0 = s
        cur += c
        prev_e = e
    if cur:
        bounds.append((cur, s0, prev_e))
    return bounds


def _openai(text: str, voice: str, speed: float, out: Path) -> None:
    raw = _http_json("https://api.openai.com/v1/audio/speech",
                     {"model": os.environ.get("SHORTS_OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice,
                      "input": text, "speed": speed, "response_format": "wav"},
                     {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
    out.write_bytes(raw)


def _piper(text: str, voice: str, speed: float, out: Path) -> None:
    model = os.environ.get("SHORTS_PIPER_MODEL") or voice
    if not Path(model).exists():
        raise ShortsError("piper needs SHORTS_PIPER_MODEL=/path/to/voice.onnx")
    run([shutil.which("piper") or "piper", "--model", model, "--length_scale", f"{1 / speed:.3f}", "--output_file", out],
        input=text.encode())


def _silent(text: str, out: Path, speed: float) -> None:
    dur = max(0.8, len(tokenize(text)) * 0.36 / speed + 0.2)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.zeros(int(dur * SR), dtype=np.int16).tobytes())


def available_engines() -> list[str]:
    eng = ["edge"]
    if os.environ.get("ELEVENLABS_API_KEY"):
        eng.append("elevenlabs")
    if os.environ.get("OPENAI_API_KEY"):
        eng.append("openai")
    if shutil.which("piper") and os.environ.get("SHORTS_PIPER_MODEL"):
        eng.append("piper")
    return eng


def resolve_voice(engine: str, voice: str | None, lang: str) -> str:
    v = voice or DEFAULT_VOICE.get(lang, "en-male-1")
    return VOICES.get(engine, {}).get(v, v)


def synth(text: str, *, lang: str, engine: str = "auto", voice: str | None = None, speed: float = 1.0) -> Speech:
    forced = os.environ.get("SHORTS_TTS")
    chain = [forced] if forced else (available_engines() if engine in ("auto", "", None) else [engine])
    errors = []
    for eng in chain:
        v = resolve_voice(eng, voice, lang)
        key = _key(eng, v, speed, text)
        hit = _cache_get(key)
        if hit:
            return hit
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "raw.audio"
            try:
                if eng == "edge":
                    words = _align_words_to_text(text, _edge_sync(text, v, speed, tmp))
                    est = False
                elif eng == "elevenlabs":
                    words = _align_words_to_text(text, _elevenlabs(text, v, speed, tmp))
                    est = False
                elif eng in ("openai", "piper", "silent"):
                    {"openai": lambda: _openai(text, v, speed, tmp), "piper": lambda: _piper(text, v, speed, tmp),
                     "silent": lambda: _silent(text, tmp, speed)}[eng]()
                    words = estimate_words(text, media_duration(tmp))
                    est = True
                else:
                    raise ShortsError(f"unknown TTS engine {eng}")
                return _cache_put(key, tmp, words, eng, v, est)
            except Exception as e:  # try the next engine in the chain
                log.warning("TTS %s failed: %s", eng, e)
                errors.append(f"{eng}: {e}")
    raise ShortsError("all TTS engines failed: " + "; ".join(errors))
