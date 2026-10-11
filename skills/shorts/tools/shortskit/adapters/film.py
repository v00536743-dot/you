"""Edits and cut-downs: find the best moments, cut on the beat, build plans.

Signals for a moment (EDITS.md):
  heatmap   YouTube "most replayed" (yt-dlp), the main signal: real viewer behaviour
  loudness  momentary loudness peaks (ffmpeg ebur128)
  cuts      scene-change density (ffmpeg scene score): action is cut faster
  speech    transcript density / sentence ends (faster-whisper if installed, or a given transcript)
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from ..config import cache_dir
from ..engine.audio import beats as audio_beats
from ..util import ShortsError, log, write_json
from .media import download_section, is_url, search, video_meta


# ---------------------------------------------------------------- signals

def loudness_curve(path: Path, step: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=metadata=0",
                        "-f", "null", "-"], capture_output=True)
    ts, ms = [], []
    for m in re.finditer(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+|-inf)", p.stderr.decode(errors="replace")):
        ts.append(float(m.group(1)))
        ms.append(-70.0 if m.group(2) == "-inf" else float(m.group(2)))
    if not ts:
        return np.array([0.0]), np.array([-70.0])
    t, v = np.array(ts), np.array(ms)
    grid = np.arange(0, t[-1], step)
    return grid, np.interp(grid, t, v)


def scene_cuts(path: Path, thr: float = 0.3) -> list[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
                        f"scale=160:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"], capture_output=True)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", p.stderr.decode(errors="replace"))]


def transcribe(path: Path, lang: str | None = None, model: str = "base") -> list[dict]:
    """Word timings with faster-whisper (optional dependency). Cached next to the media."""
    key = cache_dir("transcripts") / f"{path.stem}-{model}-{lang or 'auto'}.json"
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ShortsError("faster-whisper is not installed: `uv pip install faster-whisper`, or pass --transcript") from e
    # decode with ffmpeg ourselves: avoids PyAV version issues inside faster-whisper
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.float32)
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = wm.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True)
    words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for s in segs for w in (s.words or [])
             if w.word.strip()]
    key.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 98)
    return np.clip((x - lo) / max(1e-6, hi - lo), 0, 1)


def score_timeline(duration: float, heatmap: list[dict] | None, loud: tuple[np.ndarray, np.ndarray] | None,
                   cuts: list[float] | None, words: list[dict] | None, step: float = 0.5) -> tuple[np.ndarray, np.ndarray, dict]:
    grid = np.arange(0, max(step, duration), step)
    parts: dict[str, np.ndarray] = {}
    weights = {"heatmap": 0.5, "loudness": 0.2, "cuts": 0.2, "speech": 0.1}
    if heatmap:
        hv = np.zeros_like(grid)
        for h in heatmap:
            hv[(grid >= h["start_time"]) & (grid < h["end_time"])] = h["value"]
        parts["heatmap"] = hv
    if loud is not None and len(loud[0]) > 2:
        parts["loudness"] = _norm(np.interp(grid, loud[0], loud[1]))
    if cuts:
        dens = np.zeros_like(grid)
        for c in cuts:
            dens += np.exp(-((grid - c) ** 2) / (2 * 1.5 ** 2))
        parts["cuts"] = _norm(dens)
    if words:
        sp = np.zeros_like(grid)
        for w in words:
            sp[int(w["s"] / step):int(w["e"] / step) + 1] += 1
        parts["speech"] = _norm(sp)
    if not parts:
        raise ShortsError("no signals for moments (no heatmap and no media to analyse)")
    tot_w = sum(weights[k] for k in parts)
    score = sum(parts[k] * weights[k] for k in parts) / tot_w
    k = int(2 / step)
    smooth = np.convolve(score, np.ones(k) / k, mode="same")
    return grid, smooth, parts


def pick_windows(grid: np.ndarray, score: np.ndarray, n: int, length: float, gap: float, skip_head: float = 0.0,
                 skip_tail: float = 0.0) -> list[tuple[float, float, float]]:
    step = grid[1] - grid[0] if len(grid) > 1 else 0.5
    win = max(1, int(length / step))
    csum = np.concatenate([[0], np.cumsum(score)])
    means = (csum[win:] - csum[:-win]) / win
    starts = grid[: len(means)]
    order = np.argsort(-means)
    chosen: list[tuple[float, float, float]] = []
    end_limit = grid[-1] - skip_tail
    for i in order:
        s = float(starts[i])
        if s < skip_head or s + length > end_limit:
            continue
        if all(abs(s - c[0]) >= length + gap for c in chosen):
            chosen.append((s, s + length, float(means[i])))
        if len(chosen) >= n:
            break
    return chosen


def find_moments(url: str, n: int = 10, min_len: float = 2.5, max_len: float = 6.0, deep: bool = False,
                 plan_dir: Path | None = None) -> list[dict]:
    meta = video_meta(url) if is_url(url) else {"duration": None, "heatmap": None, "title": Path(url).name}
    heat = meta.get("heatmap")
    loud = cuts = None
    path = None
    if deep or not heat:
        path = download_section(url, max_height=240) if is_url(url) else Path(url)
        loud = loudness_curve(path)
        cuts = scene_cuts(path)
    duration = meta.get("duration") or float(loud[0][-1] if loud else 0)
    grid, score, parts = score_timeline(duration, heat, loud, cuts, None)
    length = (min_len + max_len) / 2
    wins = pick_windows(grid, score, n, length, gap=1.0, skip_head=duration * 0.02, skip_tail=duration * 0.06)
    out = []
    for s, e, sc in wins:
        i0, i1 = int(s / (grid[1] - grid[0])), int(e / (grid[1] - grid[0]))
        sig = {k: round(float(v[i0:i1].mean()), 3) for k, v in parts.items()}
        peak = s + float(np.argmax(score[i0:i1])) * (grid[1] - grid[0]) if i1 > i0 else s
        out.append({"start": round(s, 2), "end": round(e, 2), "peak": round(peak, 2), "score": round(sc, 3), "signals": sig})
    log.info("moments for %s: %d (signals: %s)", meta.get("title"), len(out), ", ".join(parts))
    return out


# ---------------------------------------------------------------- music

def music_file(src: str, plan_dir: Path | None = None) -> Path:
    if is_url(src):
        return download_section(src, audio_only=True)
    from ..plan import resolve_ref

    p = resolve_ref(src, plan_dir)
    if not p:
        raise ShortsError(f"music not found: {src}")
    return p


def music_beats(src: str) -> dict:
    p = music_file(src)
    key = cache_dir("beats") / f"{p.stem}.json"
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    b = audio_beats(p)
    key.write_text(json.dumps(b), encoding="utf-8")
    return b


def best_music_window(b: dict, length: float) -> float:
    t, r = np.array(b["energy"]["t"]), np.array(b["energy"]["rms"])
    if len(t) < 3 or t[-1] <= length:
        return 0.0
    step = t[1] - t[0]
    win = max(1, int(length / step))
    cs = np.concatenate([[0], np.cumsum(r)])
    means = (cs[win:] - cs[:-win]) / win
    i = int(np.argmax(means[: max(1, len(means))]))
    start = float(t[i])
    downs = [d for d in b["downbeats"] if d <= start + 1e-6]
    return downs[-1] if downs else start  # start on a downbeat


def beat_cuts(b: dict, start: float, length: float, target_shot: float = 1.6) -> list[float]:
    """Cut points (relative to start) on beats with a stride that gives ~target_shot second shots."""
    beat = 60.0 / max(40.0, b["tempo"])
    stride = min((1, 2, 4), key=lambda s: abs(s * beat - target_shot))
    bt = [x - start for x in b["beats"] if start - 1e-6 <= x <= start + length + 1e-6]
    if len(bt) < 2:
        n = max(1, int(length / target_shot))
        return [i * length / n for i in range(n)] + [length]
    downs = {round(d - start, 3) for d in b["downbeats"]}
    first = next((i for i, x in enumerate(bt) if round(x, 3) in downs), 0)
    cuts = [0.0] + [x for x in bt[first::stride] if 0.3 < x < length - 0.3] + [length]
    return sorted(set(round(c, 3) for c in cuts))


# ---------------------------------------------------------------- plans

def edit_plan(video: str | None, music: str, length: float = 24.0, name: str = "film-edit", title: str = "",
              lang: str = "ru", n: int = 10, query: str | None = None, links: list[str] | None = None,
              handle: str = "", platforms: list[str] | None = None, brand: str = "mono") -> dict:
    if not video:
        if not query:
            raise ShortsError("give --video URL or --query")
        res = [r for r in search(query, 10) if r.get("duration")]
        if not res:
            raise ShortsError(f"nothing found for '{query}'")
        video = max(res, key=lambda r: r["duration"])["url"]
    moments = find_moments(video, n=n, min_len=2.0, max_len=5.0)
    if not moments:
        raise ShortsError("no moments found")
    b = music_beats(music)
    m_start = best_music_window(b, length)
    cuts = beat_cuts(b, m_start, length)
    shots = list(zip(cuts, cuts[1:]))
    order = sorted(moments, key=lambda m: -m["score"])
    scenes = []
    used = []
    for i, (a, z) in enumerate(shots):
        mo = order[i % len(order)]
        dur = z - a
        rep = used.count(mo["start"])
        center = mo["peak"] + rep * (dur + 0.5)  # reuse a moment: take the next piece of it
        src_in = max(0.0, center - dur / 2)
        used.append(mo["start"])
        sc = {"id": f"shot-{i + 1:02d}", "why": f"moment score {mo['score']}", "duration": round(dur, 3),
              "source": {"type": "film", "ref": video, "in": round(src_in, 2), "out": round(src_in + dur, 2)}}
        if i == 0 and title:
            sc["on_screen_text"] = title
        scenes.append(sc)
    hero = min(len(scenes) - 1, max(1, int(len(scenes) * 0.6)))
    hs = scenes[hero]
    hs["speed"] = [{"t": 0, "rate": 0.5}]
    hs["source"]["out"] = round(hs["source"]["in"] + hs["duration"] * 0.5, 2)
    hs["why"] += "; slow-mo on the peak"
    downs = [round(d - m_start, 3) for d in b["downbeats"] if m_start <= d <= m_start + length]
    ctas = []
    if handle:
        ctas.append({"t": round(length * 0.5, 2), "duration": 2.0, "kind": "handle", "text": handle})
    if links:
        ctas.append({"t": round(max(0.0, length - 3.2), 2), "duration": 3.0, "kind": "qr", "url": links[0]})
    plan = {
        "schema_version": "1",
        "meta": {"name": name, "language": lang, "platforms": platforms or ["youtube_shorts"],
                 "duration_target": [max(10, length - 6), length + 6], "emotion": "energy", "audience": "film fans",
                 "loop": True},
        "layout": {"mode": "center_only", "cta_in_center": ctas},
        "brand": {"preset": brand},
        "captions": {"enabled": True, "max_words": 3, "highlight": "accent"},
        "audio": {"voice": {"engine": "auto"}, "music": {"source": music, "start": round(m_start, 3)}, "target_lufs": -14,
                  "sfx_auto": False},
        "fx": {"punch": downs[1:], "flash": downs[len(downs) // 2: len(downs) // 2 + 1]},
        "scenes": scenes,
        "metadata": {"topic": title, "source_video": video, "moments": moments[:n],
                     "hashtags": ["shorts", "edit", "movie", "film"] + ([re.sub(r"\W", "", title.lower())] if title else []),
                     "music": {"tempo": b["tempo"], "start": m_start, "cuts": cuts}},
    }
    return plan


def clips_plans(video: str, out_dir: Path, n: int = 3, length: float = 30.0, lang: str = "ru",
                transcript: str | None = None, layout: str = "center_only", brand: str = "mono",
                platforms: list[str] | None = None) -> list[Path]:
    """Long video -> n plans of `length` s. Windows by loudness + cuts + speech, snapped to sentence starts."""
    path = download_section(video, max_height=1080) if is_url(video) else Path(video).resolve()
    if not path.exists():
        raise ShortsError(f"video not found: {video}")
    from ..engine.clips import video_info

    info = video_info(path)
    words: list[dict] = []
    if transcript:
        words = json.loads(Path(transcript).read_text(encoding="utf-8"))
    else:
        try:
            words = transcribe(path, lang if lang != "auto" else None)
        except ShortsError as e:
            log.warning("%s; cutting without captions", e)
    heat = video_meta(video).get("heatmap") if is_url(video) else None
    loud = loudness_curve(path)
    cuts = scene_cuts(path)
    grid, score, parts = score_timeline(info["duration"], heat, loud, cuts, words)
    wins = pick_windows(grid, score, n, length, gap=2.0)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    sent_starts = [w["s"] for i, w in enumerate(words) if i == 0 or re.search(r"[.!?]$", words[i - 1]["w"])]
    for k, (s, e, sc) in enumerate(sorted(wins), 1):
        if sent_starts:
            s = min(sent_starts, key=lambda x: abs(x - s) if x <= s + 2 else 1e9)
            e = s + length
            # end on a sentence end if the clip keeps >= 60% of the target, else after the last whole word
            ends = [w["e"] for w in words if s + 0.6 * length <= w["e"] <= e + 1.5 and re.search(r"[.!?]$", w["w"])]
            if ends:
                e = max(ends)
            else:
                last = [w["e"] for w in words if s < w["e"] <= e + 0.2]
                inside = [w for w in words if w["s"] < e < w["e"]]
                if inside:
                    e = inside[0]["e"] + 0.05
                elif last and e - max(last) < 1.0:
                    e = max(last) + 0.05
        # split into 3 scenes so the plan has structure (and punch-in at each cut)
        nsc = 3
        bounds = [s + (e - s) * i / nsc for i in range(nsc + 1)]
        if words:  # never cut inside a word
            for i in range(1, nsc):
                inside = [w for w in words if w["s"] < bounds[i] < w["e"]]
                if inside:
                    bounds[i] = inside[0]["e"] + 0.01
        scenes = []
        for i in range(nsc):
            a, z = bounds[i], bounds[i + 1]
            tw = [{"w": w["w"], "s": round(w["s"] - a, 3), "e": round(min(w["e"], z) - a, 3)} for w in words if a <= w["s"] < z]
            scenes.append({"id": f"part-{i + 1}", "why": f"window score {sc:.2f}", "duration": round(z - a, 3),
                           "source": {"type": "video", "ref": str(path), "in": round(a, 3), "out": round(z, 3),
                                      "keep_audio": True},
                           **({"transcript": tw} if tw else {})})
        plan = {
            "schema_version": "1",
            "meta": {"name": f"clip-{k}", "language": lang, "platforms": platforms or ["youtube_shorts"],
                     "duration_target": [max(10, length - 10), length + 15], "loop": False},
            "layout": {"mode": layout, "cta_in_center": []},
            "brand": {"preset": brand},
            "captions": {"enabled": True, "max_words": 3, "highlight": "accent"},
            "audio": {"voice": {"engine": "auto"}, "target_lufs": -14, "sfx_auto": False},
            "fx": {"punch": [round(b - s, 3) for b in bounds[1:-1]]},
            "scenes": scenes,
            "metadata": {"source_video": str(path), "window": [round(s, 2), round(e, 2)],
                         "signals": {kk: round(float(v[int(s / 0.5):int(e / 0.5)].mean()), 3) for kk, v in parts.items()},
                         "transcript_words": len(words)},
        }
        f = out_dir / f"clip-{k}.plan.json"
        write_json(f, plan)
        files.append(f)
    return files
