"""Мост «сценарий -> plan.json» по контракту движка (contract/plan.schema.json).

Поля с приставкой x_ схема разрешает (additionalProperties не закрыт), движок
их может игнорировать. Что из них стоит сделать официальным, записано в
viora-v8/spec/CONTRACT-ISSUES.md.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

from .common import mod_root, read_json, short_link, slug
from .intake import Raw, lookup
from .script import Beat, Script, total

PANEL_TOP = 20
PANEL_BOTTOM = 18
QR_SECONDS = 3.0
HANDLE_SECONDS = 2.5
VIORA_VERSION = "8.0.0"

EMOTION_BY_RUBRIC = {"сервисы": "trust", "абуз": "excitement", "релиз": "pride", "гайд": "trust"}
AUDIENCE = {
    "ru": "школьники, студенты, начинающие разработчики и вайб-кодеры, смотрят с телефона",
    "en": "students and indie devs watching on a phone",
}


def brand_tokens(preset: str, root: Optional[str] = None) -> Dict[str, Any]:
    path = os.path.join(mod_root(root), "brand", "%s.json" % preset)
    data = read_json(path)
    if not data:
        raise ValueError("нет пресета %s в viora-shorts/brand" % preset)
    return data


def known_presets(root: Optional[str] = None) -> List[str]:
    folder = os.path.join(mod_root(root), "brand")
    return sorted(name[:-5] for name in os.listdir(folder) if name.endswith(".json"))


def _rel(path: str, base_dir: Optional[str]) -> str:
    if not base_dir:
        return path
    try:
        return os.path.relpath(path, base_dir).replace(os.sep, "/")
    except ValueError:
        return path


def _fill(actions: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    out = []
    for action in actions:
        row = copy.deepcopy(action)
        if isinstance(row.get("text"), str):
            row["text"] = row["text"].replace("{query}", query)
        out.append(row)
    return [row for row in out if not (row.get("do") == "type" and not row.get("text"))]


def generic_recipe() -> List[Dict[str, Any]]:
    """Незнакомый сайт: открыть, подвести курсор к главному, листать каждые 2 секунды."""
    return [
        {"do": "goto"},
        {"t": 0.8, "do": "move", "x": 540, "y": 700},
        {"t": 2.2, "do": "scroll", "dy": 600},
        {"t": 4.2, "do": "scroll", "dy": 600},
        {"t": 6.2, "do": "scroll", "dy": 600},
    ]


def densify(actions: List[Dict[str, Any]], seconds: float, step: float = 2.5) -> List[Dict[str, Any]]:
    """Новое событие каждые 2-3 секунды: дыры дольше трёх секунд закрываем прокруткой."""
    out = [dict(a) for a in actions]
    times = sorted({0.0} | {float(a["t"]) for a in out if "t" in a})
    filled: List[Dict[str, Any]] = []
    marks = times + [seconds]
    for left, right in zip(marks, marks[1:]):
        t = left + step
        while right - t > 0.5 and t < seconds - 0.3:
            filled.append({"t": round(t, 2), "do": "scroll", "dy": 320, "x_filler": True})
            t += step
    out.extend(filled)
    head = [a for a in out if "t" not in a]
    timed = sorted((a for a in out if "t" in a), key=lambda a: float(a["t"]))
    return head + [a for a in timed if float(a["t"]) < seconds]


def site_actions(item: Dict[str, Any], lang: str, seconds: float,
                 root: Optional[str] = None) -> Dict[str, Any]:
    row = lookup(item.get("name", ""), item.get("url"), root) or {}
    demo = row.get("demo") or {}
    query = demo.get("query_en" if lang == "en" else "query", "")
    recipe = _fill(row.get("recipe") or generic_recipe(), query)
    actions = densify(recipe, seconds)
    enter = next((float(a["t"]) for a in actions if a.get("do") == "press"), None)
    speed: List[Dict[str, float]] = []
    if enter is not None:
        # Набор и загрузку ускоряем, момент результата показываем в обычном темпе.
        speed = [{"t": 0.0, "rate": 1.6}, {"t": round(enter + 1.2, 2), "rate": 1.0}]
    sfx = [{"t": float(a["t"]), "name": "click"} for a in actions
           if a.get("do") in ("click", "press") and "t" in a]
    return {"actions": actions, "speed": speed, "sfx": sfx, "avoid": row.get("avoid", [])}


def scene_from_beat(beat: Beat, first_item: Optional[Dict[str, Any]], lang: str,
                    root: Optional[str] = None) -> Dict[str, Any]:
    item = beat.item if beat.kind == "item" else first_item
    scene: Dict[str, Any] = {"id": beat.id, "say": beat.say, "why": beat.why,
                             "x_duration_hint": beat.seconds}
    if beat.on_screen:
        scene["on_screen_text"] = beat.on_screen
    if item and item.get("url"):
        built = site_actions(item, lang, beat.seconds, root)
        actions = built["actions"]
        if beat.kind == "hook":
            # Первая секунда это уже результат: проматываем рецепт втрое быстрее.
            built["speed"] = [{"t": 0.0, "rate": 3.0}]
        if beat.kind == "cta":
            actions = densify([{"do": "goto"}, {"t": 0.6, "do": "scroll", "dy": 400}], beat.seconds)
            built["speed"], built["sfx"] = [], []
        scene["source"] = {"type": "site", "ref": item["url"], "actions": actions}
        if built["speed"]:
            scene["speed"] = built["speed"]
        sfx = list(built["sfx"])
        sfx.insert(0, {"t": 0.0, "name": "hit" if beat.kind == "hook" else "whoosh"})
        scene["sfx"] = sfx
        if built["avoid"]:
            scene["x_avoid"] = built["avoid"]
    else:
        scene["source"] = {"type": "text", "ref": beat.on_screen or beat.say,
                           "actions": densify([], beat.seconds)}
        scene["sfx"] = [{"t": 0.0, "name": "hit" if beat.kind == "hook" else "whoosh"}]
    return scene


def html_scenes(script: Script, info: Any, sound: str, speed_map: List[Dict[str, float]],
                base_dir: Optional[str]) -> List[Dict[str, Any]]:
    from .html_adapter import best_window, capture_action, demo_inputs

    ref = _rel(info.path, base_dir)
    scenes = []
    for beat in script.beats:
        if beat.kind == "chapter" and beat.item:
            start, end = beat.item["start"], beat.item["end"]
        elif beat.kind == "hook":
            start, end = best_window(info, beat.seconds)
        else:
            start, end = 0.0, beat.seconds
        actions = [capture_action(info, sound, start, end)] + demo_inputs(info, start, end)
        scene: Dict[str, Any] = {
            "id": beat.id, "say": beat.say, "why": beat.why, "x_duration_hint": beat.seconds,
            "source": {"type": "html", "ref": ref, "actions": actions},
            "sfx": [{"t": 0.0, "name": "hit" if beat.kind == "hook" else "whoosh"}],
        }
        if beat.on_screen:
            scene["on_screen_text"] = beat.on_screen
        local = [{"t": round(max(0.0, row["t"] - start), 2), "rate": row["rate"]}
                 for row in speed_map if start <= row["t"] < end]
        before = [row for row in speed_map if row["t"] < start]
        if before and not any(row["t"] == 0 for row in local):
            local.insert(0, {"t": 0.0, "rate": before[-1]["rate"]})
        if local:
            scene["speed"] = local
        scenes.append(scene)
    return scenes


def cta_flashes(duration: float, first_value_end: float, links: Dict[str, str], handle: str,
                qr: bool, lang: str, part: int = 1, parts: int = 1) -> List[Dict[str, Any]]:
    telegram = links.get("telegram") or ""
    flashes: List[Dict[str, Any]] = []
    t_handle = min(max(first_value_end, duration * 0.42), duration * 0.58)
    flashes.append({"t": round(t_handle, 2), "duration": HANDLE_SECONDS, "kind": "handle",
                    "text": "%s | %s" % (handle, short_link(telegram)), "url": telegram})
    if parts > 1 and part < parts:
        t_text = duration - QR_SECONDS - 0.6 - 2.0 if qr else duration - 2.5
        if t_text > t_handle + HANDLE_SECONDS + 0.3:
            flashes.append({"t": round(t_text, 2), "duration": 2.0, "kind": "text",
                            "text": ("ЧАСТЬ %d В КАНАЛЕ" if lang == "ru" else "PART %d ON THE CHANNEL") % (part + 1)})
    if qr and telegram:
        flashes.append({"t": round(duration - QR_SECONDS - 0.5, 2), "duration": QR_SECONDS,
                        "kind": "qr", "url": telegram, "text": short_link(telegram)})
    return flashes


def build(script: Script, prefs: Dict[str, Any], raw: Optional[Raw] = None, *,
          name: Optional[str] = None, html_info: Any = None, sound: str = "sfx",
          speed_map: Optional[List[Dict[str, float]]] = None, base_dir: Optional[str] = None,
          root: Optional[str] = None) -> Dict[str, Any]:
    """Собрать план. prefs уже с умолчаниями (prefs.effective)."""
    from .prefs import top_source

    lang = script.lang
    preset = (prefs.get("brand") or {}).get("preset", "viora")
    register = (prefs.get("brand") or {}).get("register", "minimal")
    tokens = brand_tokens(preset, root)
    links = dict(prefs.get("links") or {})
    handle = links.get("handle") or "BADVINO"
    notes: List[str] = []

    # Раскладку не выбрал автор: три панели для сервисов, только центр для HTML (COMMON.md раздел 1).
    mode = prefs.get("layout") or ("center_only" if html_info else "three")
    top = top_source(prefs)
    if mode in ("three", "top_center") and not top:
        mode = "center_bottom" if mode == "three" else "center_only"
        notes.append("top")
    layout: Dict[str, Any] = {"mode": mode}
    if mode in ("three", "top_center"):
        layout["top"] = {"height_pct": PANEL_TOP, "source": _rel(top, base_dir) if os.path.exists(str(top)) else top}
    if mode in ("three", "center_bottom"):
        layout["bottom"] = {"height_pct": PANEL_BOTTOM, "handle": handle,
                            "links": [links[k] for k in ("telegram", "youtube") if links.get(k)]}

    if html_info is not None:
        scenes = html_scenes(script, html_info, sound, speed_map or [], base_dir)
    else:
        first_item = next((b.item for b in script.beats if b.kind == "item" and b.item), None)
        scenes = [scene_from_beat(beat, first_item, lang, root) for beat in script.beats]

    duration = total(script)
    first_value_end = 0.0
    clock = 0.0
    for beat in script.beats:
        clock += beat.seconds
        if beat.kind in ("item", "chapter"):
            first_value_end = clock
            break
    layout["cta_in_center"] = cta_flashes(duration, first_value_end, links, handle,
                                          bool(prefs.get("qr", True)), lang, script.part, script.parts)

    voice = prefs.get("voice") or {}
    audio: Dict[str, Any] = {
        "voice": {"engine": voice.get("engine", "auto"), "voice": voice.get("voice", ""),
                  "speed": float(voice.get("speed", 1.05))},
        "target_lufs": -14,
    }
    music = (prefs.get("music") or {}).get("source")
    if music:
        audio["music"] = {"source": _rel(music, base_dir) if os.path.exists(music) else music,
                          "duck_db": float((prefs.get("music") or {}).get("duck_db", -10))}

    fonts_dir = os.path.join(mod_root(root), "brand")
    fonts = {role: _rel(os.path.join(fonts_dir, path), base_dir)
             for role, path in tokens.get("fonts", {}).items() if role in ("display", "body")}
    rubric = raw.rubric if raw else None
    title_seed = name or (raw.hook if raw and raw.hook else script.beats[0].on_screen)
    plan: Dict[str, Any] = {
        "schema_version": "1",
        "meta": {
            "name": slug(title_seed),
            "language": lang,
            "platforms": list(prefs.get("platforms") or ["youtube_shorts"]),
            "duration_target": list(script.duration_target),
            "emotion": EMOTION_BY_RUBRIC.get(rubric or "", tokens.get("emotion_default", "trust")),
            "audience": AUDIENCE.get(lang, AUDIENCE["en"]),
            "loop": True,
        },
        "layout": layout,
        "brand": {"preset": preset, "palette": dict(tokens["palette"]), "fonts": fonts},
        "captions": {"enabled": True, "max_words": 3, "highlight": "accent" if preset != "mono" else "none",
                     "subs": dict(script.subs)},
        "audio": audio,
        "scenes": scenes,
        "metadata": {},
        "x_viora": {
            "version": VIORA_VERSION,
            "register": register,
            "part": script.part,
            "parts": script.parts,
            "estimated_seconds": duration,
            "pending": notes,
        },
    }
    if script.parts > 1:
        plan["meta"]["name"] = "%s-part-%d" % (plan["meta"]["name"][:40].strip("-"), script.part)
    return plan
