#!/usr/bin/env python3
"""SHORTS: one entry point for the agent.

  python3 tools/shorts.py doctor                       what is installed, which TTS / image generator works
  python3 tools/shorts.py prefs show|set k=v|skip k|done k|reset|remind|history
  python3 tools/shorts.py intake [--lang ru]           the first-run questions (only what is missing in prefs)
  python3 tools/shorts.py validate plan.json           schema + rule lint
  python3 tools/shorts.py plan --from prefs --source site --ref URL ... -o plan.json   plan skeleton
  python3 tools/shorts.py render plan.json --out DIR   build the video (public interface)
  python3 tools/shorts.py qa DIR                       QA gate, writes qa.json / qa.md / contact sheet (public interface)
  python3 tools/shorts.py meta DIR [--topic ...]       titles x5-7, one description, pinned comment, TikTok caption
  python3 tools/shorts.py cover DIR [--image file]     cover: 3 variants or a ready prompt
  python3 tools/shorts.py site-probe URL               check a site (protection, screenshot, clickable elements)
  python3 tools/shorts.py yt-search "query" | yt-meta URL | moments URL | beats FILE|URL
  python3 tools/shorts.py edit --video URL --music URL -o plan.json      film edit plan (beat-cut)
  python3 tools/shorts.py clips --video FILE|URL -o plan.json            cut a long video into shorts plans
  python3 tools/shorts.py all plan.json --out DIR      render + qa + meta + cover
Exit codes: 0 ok, 1 QA failed / plan errors, 2 usage or runtime error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shortskit.util import ShortsError  # noqa: E402


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2) if not isinstance(obj, str) else obj)


def cmd_validate(a) -> int:
    from shortskit import plan as P

    raw, d = P.load(a.plan)
    issues = P.check(raw, d)
    for i in issues:
        print(i)
    n = len(P.errors(issues))
    print(f"{'OK' if n == 0 else 'FAIL'}: {n} errors, {len(issues) - n} warnings")
    return 1 if n else 0


def cmd_render(a) -> int:
    from shortskit.engine.render import render

    m = render(a.plan, a.out, force=a.force, keep_work=a.keep_work)
    skipped = [f"{s['id']}: {s['skipped']}" for s in m["scenes"] if s["skipped"]]
    print(f"video: {Path(a.out) / m['video']}  ({m['duration']}s, render {m['render_seconds']}s)")
    for s in skipped:
        print(f"skipped scene {s}")
    for s in m["scenes"]:
        for n in s["notes"]:
            print(f"note [{s['id']}]: {n}")
    return 0


def cmd_qa(a) -> int:
    from shortskit.qa.gate import run_gate

    rep = run_gate(Path(a.dir), strict=a.strict)
    print(Path(a.dir) / "qa.md")
    print(rep["summary"])
    return 0 if rep["passed"] else 1


def cmd_meta(a) -> int:
    from shortskit.meta.packaging import package_dir

    res = package_dir(Path(a.dir), topic=a.topic, hashtags=a.hashtags, cta=a.cta)
    print((Path(a.dir) / "metadata.md").read_text(encoding="utf-8"))
    return 0 if res["ok"] else 1


def cmd_cover(a) -> int:
    from shortskit.meta.cover import cover_dir

    res = cover_dir(Path(a.dir), image=a.image, text=a.text, generate=not a.no_generate)
    _print(res)
    return 0


def cmd_all(a) -> int:
    rc = cmd_render(a)
    if rc:
        return rc
    a.dir = a.out
    a.strict = False
    meta_args = argparse.Namespace(dir=a.out, topic=None, hashtags=None, cta=None)
    cmd_meta(meta_args)
    cover_args = argparse.Namespace(dir=a.out, image=None, text=None, no_generate=False)
    cmd_cover(cover_args)
    return cmd_qa(a)


def cmd_prefs(a) -> int:
    from shortskit import memory as M

    if a.action == "show":
        _print(M.load())
    elif a.action == "set":
        for kv in a.items:
            k, _, v = kv.partition("=")
            M.set_value(k, M.parse_value(v))
        _print(M.load())
    elif a.action == "skip":
        for k in a.items:
            M.skip(k)
        _print(M.load()["pending"])
    elif a.action == "done":
        for k in a.items:
            M.close_pending(k)
        _print(M.load()["pending"])
    elif a.action == "reset":
        M.reset()
        print("prefs cleared")
    elif a.action == "remind":
        print(M.reminder_line(M.load()) or "")
    elif a.action == "history":
        _print(M.history())
    elif a.action == "summary":
        print(M.summary_line(M.load()))
    return 0


def cmd_intake(a) -> int:
    from shortskit import memory as M

    print(M.intake_message(M.load(), a.lang))
    return 0


def cmd_plan(a) -> int:
    from shortskit.planner import skeleton

    p = skeleton(source=a.source, refs=a.ref or [], name=a.name, topic=a.topic or "")
    Path(a.output).write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(a.output)
    return 0


def cmd_doctor(a) -> int:
    from shortskit.doctor import doctor

    rep = doctor()
    _print(rep)
    return 0 if rep["ok"] else 2


def cmd_site_probe(a) -> int:
    import asyncio

    from shortskit.adapters.site import probe

    _print(asyncio.run(probe(a.url, Path(a.out))))
    return 0


def cmd_yt_search(a) -> int:
    from shortskit.adapters.media import search

    _print(search(a.query, a.n))
    return 0


def cmd_yt_meta(a) -> int:
    from shortskit.adapters.media import video_meta

    m = video_meta(a.url)
    m.pop("heatmap", None) if not a.heatmap else None
    _print(m)
    return 0


def cmd_moments(a) -> int:
    from shortskit.adapters.film import find_moments

    _print(find_moments(a.url, n=a.n, min_len=a.min_len, max_len=a.max_len, deep=a.deep))
    return 0


def cmd_beats(a) -> int:
    from shortskit.adapters.film import music_beats

    b = music_beats(a.src)
    b.pop("energy", None)
    _print(b)
    return 0


def cmd_edit(a) -> int:
    from shortskit.adapters.film import edit_plan

    p = edit_plan(video=a.video, music=a.music, length=a.length, name=a.name, title=a.title, lang=a.lang,
                  n=a.n, query=a.query, links=a.link or None, handle=a.handle or "", brand=a.brand,
                  platforms=a.platforms)
    Path(a.output).write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(a.output)
    return 0


def cmd_clips(a) -> int:
    from shortskit.adapters.film import clips_plans

    files = clips_plans(video=a.video, out_dir=Path(a.output), n=a.n, length=a.length, lang=a.lang,
                        transcript=a.transcript, brand=a.brand, platforms=a.platforms)
    _print([str(f) for f in files])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shorts", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate"); s.add_argument("plan"); s.set_defaults(fn=cmd_validate)
    for name, fn in (("render", cmd_render), ("all", cmd_all)):
        s = sub.add_parser(name); s.add_argument("plan"); s.add_argument("--out", required=True)
        s.add_argument("--force", action="store_true", help="render even if the plan has errors (QA will fail)")
        s.add_argument("--keep-work", action="store_true"); s.set_defaults(fn=fn)
    s = sub.add_parser("qa"); s.add_argument("dir"); s.add_argument("--strict", action="store_true"); s.set_defaults(fn=cmd_qa)
    s = sub.add_parser("meta"); s.add_argument("dir"); s.add_argument("--topic"); s.add_argument("--hashtags", nargs="*")
    s.add_argument("--cta"); s.set_defaults(fn=cmd_meta)
    s = sub.add_parser("cover"); s.add_argument("dir"); s.add_argument("--image"); s.add_argument("--text")
    s.add_argument("--no-generate", action="store_true"); s.set_defaults(fn=cmd_cover)
    s = sub.add_parser("prefs"); s.add_argument("action", choices=["show", "set", "skip", "done", "reset", "remind", "history", "summary"])
    s.add_argument("items", nargs="*"); s.set_defaults(fn=cmd_prefs)
    s = sub.add_parser("intake"); s.add_argument("--lang", default=None); s.set_defaults(fn=cmd_intake)
    s = sub.add_parser("plan"); s.add_argument("--source", required=True, choices=["site", "html", "video", "film", "text", "images"])
    s.add_argument("--ref", nargs="*"); s.add_argument("--name", default="short"); s.add_argument("--topic")
    s.add_argument("-o", "--output", default="plan.json"); s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("doctor"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("site-probe"); s.add_argument("url"); s.add_argument("--out", default="out/probe"); s.set_defaults(fn=cmd_site_probe)
    s = sub.add_parser("yt-search"); s.add_argument("query"); s.add_argument("-n", type=int, default=10); s.set_defaults(fn=cmd_yt_search)
    s = sub.add_parser("yt-meta"); s.add_argument("url"); s.add_argument("--heatmap", action="store_true"); s.set_defaults(fn=cmd_yt_meta)
    s = sub.add_parser("moments"); s.add_argument("url"); s.add_argument("-n", type=int, default=10)
    s.add_argument("--min-len", type=float, default=2.5); s.add_argument("--max-len", type=float, default=6.0)
    s.add_argument("--deep", action="store_true", help="also download a low-res copy for loudness and scene cuts")
    s.set_defaults(fn=cmd_moments)
    s = sub.add_parser("beats"); s.add_argument("src"); s.set_defaults(fn=cmd_beats)
    s = sub.add_parser("edit"); s.add_argument("--video"); s.add_argument("--query"); s.add_argument("--music", required=True)
    s.add_argument("--length", type=float, default=24.0); s.add_argument("--name", default="film-edit")
    s.add_argument("--title", default=""); s.add_argument("--lang", default="ru"); s.add_argument("-n", type=int, default=10)
    s.add_argument("--handle"); s.add_argument("--link", nargs="*"); s.add_argument("--brand", default="mono")
    s.add_argument("--platforms", nargs="*", default=["youtube_shorts"])
    s.add_argument("-o", "--output", default="plan.json"); s.set_defaults(fn=cmd_edit)
    s = sub.add_parser("clips"); s.add_argument("--video", required=True); s.add_argument("-n", type=int, default=3)
    s.add_argument("--length", type=float, default=30.0); s.add_argument("--lang", default="ru")
    s.add_argument("--transcript", help="words json [{w,s,e}] (from whisper); without it moments come from loudness and cuts")
    s.add_argument("--brand", default="mono"); s.add_argument("--platforms", nargs="*", default=["youtube_shorts"])
    s.add_argument("-o", "--output", default="out/clips"); s.set_defaults(fn=cmd_clips)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        return a.fn(a)
    except ShortsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
