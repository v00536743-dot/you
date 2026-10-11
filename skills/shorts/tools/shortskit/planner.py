"""Plan skeletons from prefs: the agent fills say / on_screen_text / actions, the script fills the rules."""
from __future__ import annotations

import re

from . import memory as M


def _lang(p: dict) -> str:
    lang = p.get("language")
    if isinstance(lang, dict):
        return (lang.get("video") or lang.get("chat") or "ru")[:2]
    return (lang or "ru")[:2]


def _links(p: dict) -> list[str]:
    links = p.get("links") or {}
    if isinstance(links, dict):
        return [v for v in links.values() if isinstance(v, str) and v.startswith("http")]
    return [v for v in links if isinstance(v, str)]


def skeleton(source: str, refs: list[str], name: str = "short", topic: str = "") -> dict:
    p = M.load()
    lang = _lang(p)
    platforms = p.get("platforms") or ["youtube_shorts"]
    mode = p.get("layout") or ("center_only" if source in ("film", "video") else "three")
    panels = p.get("panels") or {}
    links = _links(p)
    handle = (p.get("handle") or panels.get("handle") or "").lstrip("@")
    layout: dict = {"mode": mode, "cta_in_center": []}
    if mode in ("three", "top_center"):
        layout["top"] = {"height_pct": 20, "source": panels.get("top") or "assets/footage/own-game-loop.mp4"}
    if mode in ("three", "center_bottom"):
        layout["bottom"] = {"height_pct": 16, "handle": handle, "links": links[:1]}
    target = [20, 40]
    if handle:
        layout["cta_in_center"].append({"t": 14, "duration": 2.5, "kind": "handle", "text": handle})
    if links and p.get("qr", True):
        layout["cta_in_center"].append({"t": 27, "duration": 3, "kind": "qr", "url": links[0]})
    scenes = []
    say_hook = "TODO: result or question in the first second, no greeting" if lang != "ru" else \
        "TODO: результат или вопрос в первую секунду, без приветствия"
    if source == "site":
        for i, r in enumerate(refs or ["https://example.com"]):
            scenes.append({"id": "hook" if i == 0 else f"site-{i}", "say": say_hook if i == 0 else "TODO",
                           "on_screen_text": "TODO 2-4 WORDS" if i == 0 else "", "why": "result first" if i == 0 else "demo",
                           "source": {"type": "site", "ref": r, "viewport": "mobile",
                                      "actions": [{"do": "goto"}, {"do": "dismiss_cookies"}, {"do": "scroll", "dy": 600, "t": 2.0}]}})
    elif source in ("html", "images", "video", "film"):
        for i, r in enumerate(refs or ["TODO"]):
            src: dict = {"type": source, "ref": r}
            if source == "images":
                src = {"type": "images", "images": [r], "focus": [0.5, 0.4]}
            if source in ("video", "film"):
                src.update({"in": 0, "out": 6})
            scenes.append({"id": f"s{i + 1}", "say": say_hook if i == 0 else "TODO", "why": "TODO", "source": src,
                           **({"on_screen_text": "TODO"} if i == 0 else {})})
    else:
        scenes.append({"id": "hook", "say": say_hook, "on_screen_text": "TODO", "why": "result first",
                       "source": {"type": "text", "ref": topic or "TODO | phrase two | phrase three"}})
    br = p.get("brand") or {"preset": "mono"}
    plan = {
        "schema_version": "1",
        "meta": {"name": re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "short", "language": lang,
                 "platforms": platforms, "duration_target": target, "emotion": "trust", "audience": "TODO", "loop": True},
        "layout": layout,
        "brand": br if isinstance(br, dict) else {"preset": str(br)},
        "captions": {"enabled": True, "max_words": 3, "highlight": "accent", "subs": {}},
        "audio": {"voice": p.get("voice") or {"engine": "auto", "speed": 1.05},
                  "music": {"source": (p.get("music") or {}).get("source", "assets/audio/bed.mp3"), "duck_db": -10},
                  "target_lufs": -14},
        "scenes": scenes,
        "metadata": {"topic": topic},
    }
    return plan
