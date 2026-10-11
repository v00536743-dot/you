"""Adapters `video` and `film`: cut a segment of a file or a YouTube video into the centre panel.

Downloads use yt-dlp (cached). Only the needed seconds are downloaded (--download-sections).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from ..config import cache_dir
from ..engine.clips import SpeedMap, read_frames, retime_stream, video_info, write_frames_clip
from ..util import ShortsError, log, retry, run
from .site import Capture

FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b"


def ytdlp_base() -> list[str]:
    exe = shutil.which("yt-dlp")
    base = [exe] if exe else ["python3", "-m", "yt_dlp"]
    base += ["--no-playlist", "--no-warnings", "--quiet", "--no-progress"]
    if shutil.which("deno") is None and shutil.which("node"):
        base += ["--js-runtimes", "node"]
    if os.environ.get("SHORTS_YTDLP_COOKIES"):
        base += ["--cookies", os.environ["SHORTS_YTDLP_COOKIES"]]
    return base


def is_url(ref: str) -> bool:
    return ref.startswith(("http://", "https://"))


@retry(times=3, delay=3)
def download_section(url: str, start: float | None = None, end: float | None = None, audio_only: bool = False,
                     max_height: int = 1080) -> Path:
    key = hashlib.sha1(f"{url}|{start}|{end}|{audio_only}|{max_height}".encode()).hexdigest()[:16]
    d = cache_dir("downloads")
    found = list(d.glob(f"{key}.*"))
    found = [f for f in found if f.suffix in (".mp4", ".m4a", ".webm", ".mkv", ".wav", ".opus", ".mp3")]
    if found:
        return found[0]
    cmd = ytdlp_base() + ["-o", str(d / f"{key}.%(ext)s")]
    if audio_only:
        cmd += ["-f", "ba/b", "-x", "--audio-format", "wav"]
    else:
        cmd += ["-f", FORMAT.replace("1080", str(max_height)), "--merge-output-format", "mp4"]
    if start is not None and end is not None:
        cmd += ["--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts"]
    cmd.append(url)
    run(cmd, timeout=900)
    found = [f for f in d.glob(f"{key}.*") if f.suffix != ".part"]
    if not found:
        raise ShortsError(f"yt-dlp produced no file for {url}")
    return found[0]


def video_meta(url: str) -> dict:
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    p = cache_dir("meta") / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    out = run(ytdlp_base() + ["--skip-download", "--dump-single-json", url], timeout=180)
    data = json.loads(out)
    keep = {k: data.get(k) for k in ("id", "title", "duration", "channel", "uploader", "chapters", "heatmap",
                                     "view_count", "webpage_url", "subtitles", "automatic_captions", "width", "height")}
    keep["subtitles"] = sorted((data.get("subtitles") or {}).keys())
    keep["automatic_captions"] = sorted((data.get("automatic_captions") or {}).keys())[:20]
    p.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    return keep


def search(query: str, n: int = 10) -> list[dict]:
    out = run(ytdlp_base() + ["--flat-playlist", "--dump-json", f"ytsearch{n}:{query}"], timeout=180)
    res = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        res.append({"id": d.get("id"), "title": d.get("title"), "duration": d.get("duration"),
                    "channel": d.get("channel") or d.get("uploader"), "url": d.get("url") or f"https://www.youtube.com/watch?v={d.get('id')}",
                    "views": d.get("view_count")})
    return res


def local_or_download(ref: str, plan_dir: Path | None, start: float | None = None, end: float | None = None) -> tuple[Path, float]:
    """Return (file, offset inside file where `start` is)."""
    if is_url(ref):
        if start is not None and end is not None:
            return download_section(ref, max(0.0, start - 0.5), end + 0.5), min(0.5, start)
        return download_section(ref), start or 0.0
    from ..plan import resolve_ref

    p = resolve_ref(ref, plan_dir)
    if not p:
        raise ShortsError(f"video not found: {ref}")
    return p, start or 0.0


def retime_audio(src: Path, start: float, speed: SpeedMap, out_len: float, out: Path) -> Path:
    """Cut the source audio and follow the same speed map (atempo per segment)."""
    segs = []
    t_out = 0.0
    i = 0
    while t_out < out_len - 1e-3 and i < 64:
        k = max(j for j, o in enumerate(speed.out) if o <= t_out + 1e-9)
        nxt_out = speed.out[k + 1] if k + 1 < len(speed.out) else out_len
        seg_out = min(nxt_out, out_len) - t_out
        s0 = speed.src_at(t_out)
        segs.append((start + s0, start + s0 + seg_out * speed.rate[k], speed.rate[k]))
        t_out += seg_out
        i += 1
    parts, labels = [], []
    for n, (a, b, r) in enumerate(segs):
        tempo = []
        rr = r
        while rr > 2.0:
            tempo.append("atempo=2.0")
            rr /= 2.0
        while rr < 0.5:
            tempo.append("atempo=0.5")
            rr /= 0.5
        tempo.append(f"atempo={rr:.5f}")
        parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,{','.join(tempo)}[a{n}]")
        labels.append(f"[a{n}]")
    fc = ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1,apad=whole_dur={out_len:.3f},atrim=0:{out_len:.3f}[out]"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-filter_complex", fc, "-map", "[out]", "-ar", 48000, "-ac", 2, out])
    return out


def capture(scene: dict, w: int, h: int, fps: int, out_len: float, work: Path, plan_dir: Path | None) -> Capture:
    src = scene["source"]
    ref = src.get("ref") or ""
    s_in = float(src.get("in", 0.0))
    s_out = src.get("out")
    speed = SpeedMap(scene.get("speed"))
    need_src = speed.src_at(out_len)
    end = float(s_out) if s_out is not None else s_in + need_src
    path, offset = local_or_download(ref, plan_dir, s_in, max(end, s_in + need_src) if is_url(ref) else None)
    info = video_info(path)
    notes = []
    if offset + need_src > info["duration"] + 0.05:
        notes.append(f"source shorter than needed ({info['duration'] - offset:.1f}s < {need_src:.1f}s), last frame held")
    frames = read_frames(path, w, h, start=offset, duration=need_src + 0.5, focus_x=float(src.get("crop_x", 0.5)))
    out = work / f"center-{scene['id']}.mp4"
    n_out = max(1, int(round(out_len * fps)))
    write_frames_clip(out, w, h, fps, retime_stream(frames, info["fps"], n_out, fps, speed))
    audio = None
    if src.get("keep_audio") and info["has_audio"]:
        audio = retime_audio(path, offset, speed, out_len, work / f"src-{scene['id']}.wav")
    log.debug("video scene %s from %s @%.2f", scene["id"], path.name, offset)
    return Capture(out, notes=notes, audio=audio)
