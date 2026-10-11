"""User memory: prefs.json (settings + pending reminders), history.json (videos made), experiments and metrics.

All files live in $SHORTS_MEMORY (default <skill>/memory). prefs.json and history.json are git-ignored.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .config import memory_dir
from .util import read_json, write_json

KEYS = ("language", "platforms", "source", "layout", "panels", "links", "qr", "brand", "voice", "music", "title_style")
DEFAULTS: dict[str, Any] = {
    "language": {"chat": "ru", "video": "ru"},
    "platforms": ["youtube_shorts"],
    "layout": "three",
    "brand": {"preset": "mono"},
    "voice": {"engine": "auto", "voice": None, "speed": 1.05},
    "music": {"source": "assets/audio/bed.mp3"},
    "qr": True,
}
REMIND = {
    "ru": {
        "language": "язык роликов", "platforms": "платформы", "source": "откуда сырьё", "layout": "раскладка",
        "panels": "что в верхней и нижней панели", "links": "ссылки и ники для рекламы", "qr": "нужен ли QR",
        "brand": "стиль бренда (пока mono)", "voice": "голос", "music": "музыка", "title_style": "стиль названий",
    },
    "en": {
        "language": "video language", "platforms": "platforms", "source": "raw material", "layout": "layout",
        "panels": "top and bottom panel content", "links": "links and handles", "qr": "QR or not",
        "brand": "brand style (mono for now)", "voice": "voice", "music": "music", "title_style": "title style",
    },
}


def prefs_path() -> Path:
    return memory_dir() / "prefs.json"


def history_path() -> Path:
    return memory_dir() / "history.json"


def empty() -> dict:
    return {"version": 1, "pending": [], "rejected": [], "chosen_titles": [], "updated": None}


def load() -> dict:
    p = prefs_path()
    if not p.exists():
        return empty()
    data = read_json(p)
    base = empty()
    base.update(data)
    return base


def save(prefs: dict) -> dict:
    prefs["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    write_json(prefs_path(), prefs)
    return prefs


def parse_value(v: str) -> Any:
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        if "," in v and not v.startswith("http"):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


def set_value(key: str, value: Any) -> dict:
    p = load()
    cur = p
    parts = key.split(".")
    for k in parts[:-1]:
        cur = cur.setdefault(k, {})
    cur[parts[-1]] = value
    top = parts[0]
    if top in p["pending"]:
        p["pending"].remove(top)
    return save(p)


def skip(key: str) -> dict:
    """User skipped a question: use the default now, remind at the end of every video until closed."""
    p = load()
    if key not in p["pending"]:
        p["pending"].append(key)
    if key in DEFAULTS and key not in p:
        p[key] = DEFAULTS[key]
    return save(p)


def close_pending(key: str) -> dict:
    p = load()
    if key in p["pending"]:
        p["pending"].remove(key)
    return save(p)


def reset() -> None:
    for f in (prefs_path(), history_path()):
        f.unlink(missing_ok=True)


def chat_lang(p: dict) -> str:
    lang = p.get("language")
    if isinstance(lang, dict):
        return (lang.get("chat") or "ru")[:2]
    return (lang or "ru")[:2]


def missing(p: dict) -> list[str]:
    return [k for k in KEYS if k not in p and k not in p["pending"] and k != "title_style"]


def reminder_line(p: dict) -> str:
    if not p["pending"]:
        return ""
    lang = chat_lang(p)
    names = [REMIND.get(lang, REMIND["en"]).get(k, k) for k in p["pending"]]
    if lang == "ru":
        return f"Не заполнено: {', '.join(names)}. Дать сейчас?"
    return f"Not set yet: {', '.join(names)}. Give it now?"


def summary_line(p: dict) -> str:
    lang = chat_lang(p)
    parts = []
    for k in ("language", "platforms", "layout", "brand", "voice", "links", "qr"):
        if k in p:
            v = p[k]
            if isinstance(v, dict):
                v = ", ".join(f"{a}={b}" for a, b in v.items() if b is not None)
            elif isinstance(v, list):
                v = ", ".join(map(str, v))
            parts.append(f"{k}: {v}")
    body = "; ".join(parts)
    if lang == "ru":
        return f"Беру настройки как в прошлый раз: {body}. Менять?"
    return f"Using the same settings as last time: {body}. Change anything?"


QUESTIONS = {
    "ru": {
        "language": "1. Язык общения и роликов: русский, английский или другой? (озвучка, субтитры, названия будут на нём)",
        "platforms": "2. Платформы: YouTube Shorts, TikTok, Reels, обычный YouTube?",
        "source": "3. Откуда сырьё: сайты/сервисы (ссылки), HTML-файл, своё длинное видео, фильм или ролики с YouTube, текст/тема, скриншоты?",
        "layout": ("4. Раскладка 1080x1920: верхняя панель (геймплей или другое движение, до 20%), центр (главное, от 55%), "
                   "нижняя панель (ник, Телеграм, соцсети, до 20%). Можно убрать верх, низ или обе. Можно пропустить, напомню."),
        "links": "5. Ссылки и ники для рекламы и описания (Телеграм, YouTube, сайт, соцсети). Нужен QR? (QR всплывает в центре, рядом всегда текстовая ссылка)",
        "brand": "6. Свой стиль есть? а) файлы: логотип, цвета, шрифты; б) ссылка на канал/сайт, я соберу токены; в) пресет: mono, editorial, terminal, punch, viora; г) не сейчас (ставлю mono и напомню).",
        "voice": "7. Голос и музыка: мужской/женский, свой трек или ссылка на YouTube, или «выбери сам».",
    },
    "en": {
        "language": "1. Chat and video language: English, Russian, other? (voice, captions, titles will use it)",
        "platforms": "2. Platforms: YouTube Shorts, TikTok, Reels, regular YouTube?",
        "source": "3. Raw material: websites (links), an HTML file, your long video, a film or YouTube videos, text/topic, screenshots?",
        "layout": ("4. Layout 1080x1920: top panel (gameplay or other motion, up to 20%), centre (the main thing, 55%+), "
                   "bottom panel (handle, Telegram, socials, up to 20%). Top, bottom or both can be removed. You can skip, I will remind you."),
        "links": "5. Links and handles for the CTA and description. Need a QR? (QR flashes in the centre, always with a text link)",
        "brand": "6. Do you have a style? a) files: logo, colours, fonts; b) a link to your channel/site, I will build tokens; c) preset: mono, editorial, terminal, punch, viora; d) not now (mono + reminder).",
        "voice": "7. Voice and music: male/female, your track or a YouTube link, or 'you choose'.",
    },
}


def intake_message(p: dict, lang: str | None = None) -> str:
    lang = (lang or chat_lang(p))[:2]
    q = QUESTIONS.get(lang, QUESTIONS["en"])
    need = [k for k in q if k not in p and k not in p["pending"]]
    if "voice" in need and "music" in p:
        pass
    if not need:
        return summary_line(p) + ("\n" + reminder_line(p) if p["pending"] else "")
    head = "Пара вопросов перед стартом (можно ответить коротко или пропустить любой):" if lang == "ru" else \
        "A few questions before we start (answer briefly or skip any):"
    return "\n".join([head] + [q[k] for k in need])


# ---------------------------------------------------------------- history and behaviour

def history() -> list[dict]:
    p = history_path()
    return read_json(p) if p.exists() else []


def record_video(name: str, first_hash: str, out_dir: Path) -> None:
    h = [x for x in history() if x.get("name") != name]
    title = ""
    meta = Path(out_dir) / "metadata.json"
    if meta.exists():
        title = read_json(meta).get("recommended_title", "")
    h.append({"name": name, "first_hash": first_hash, "title": title, "dir": str(out_dir),
              "date": dt.date.today().isoformat()})
    write_json(history_path(), h[-200:])


def remember_choice(kind: str, value: Any) -> dict:
    """kind: chosen_title | rejected (anything the user turned down: a style, a title, a voice)."""
    p = load()
    key = "chosen_titles" if kind == "chosen_title" else "rejected"
    p.setdefault(key, []).append({"value": value, "date": dt.date.today().isoformat()})
    p[key] = p[key][-50:]
    return save(p)
