"""Настройки роликов: memory/video-prefs.json.

Профиль автора (memory/profile.md) не трогаем. Здесь только то, что нужно роликам:
язык, площадки, раскладка, ссылки, QR, стиль, голос, музыка и что автор выбирал.

Правило из COMMON.md раздел 9: чего нет, спрашиваем ОДНИМ сообщением. Пропущенное
ставим по умолчанию, кладём в pending и напоминаем одной строкой в конце каждого ролика.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional, Tuple

from .common import brand_links, memory_path, read_json, write_json, mod_root

FILE = "video-prefs.json"
STORE_VERSION = 1

MODES = ("three", "top_center", "center_bottom", "center_only")
PLATFORMS = ("youtube_shorts", "tiktok", "reels", "youtube")
SOURCES = ("site", "html", "video", "film", "text", "images")
HANDLE = "BADVINO"

# Вопросы в порядке COMMON.md раздел 9. Пункт 8 (генератор картинок) агент
# определяет сам по переменным окружения, автора не спрашиваем.
QUESTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("language",
     "Язык роликов: русский или английский? (озвучка, субтитры, название, описание)",
     "Video language: Russian or English? (voice, captions, title, description)"),
    ("platforms",
     "Площадки: YouTube Shorts, TikTok, Reels, обычный YouTube? Можно несколько.",
     "Platforms: YouTube Shorts, TikTok, Reels, regular YouTube? Several are fine."),
    ("sources",
     "Откуда чаще сырьё: сайты и сервисы, HTML-файл, свои длинные видео, текст, скриншоты?",
     "Usual raw material: sites, an HTML file, your long videos, text, screenshots?"),
    ("layout",
     "Раскладка: три панели (верх, центр, низ), без верха, без низа или только центр? "
     "Что ставим в верхнюю панель (своё видео, геймплей)? Можно пропустить.",
     "Layout: three panels, no top, no bottom, or center only? What goes in the top panel "
     "(your own gameplay)? You can skip."),
    ("qr",
     "Ссылки беру из brand.md (Телеграм, YouTube, ник BADVINO). QR на Телеграм в конце ставить?",
     "Links come from brand.md (Telegram, YouTube, BADVINO). Add a Telegram QR at the end?"),
    ("brand",
     "Стиль: свой фирменный VIORA (чёрный, тонкий шрифт, один красный акцент), строго "
     "чёрно-белый mono, или есть свои файлы и ссылка на стиль?",
     "Style: VIORA (black, thin type, one red accent), strict black and white mono, "
     "or your own files and a style link?"),
    ("voice",
     "Голос и музыка: мужской, женский или «выбери сам»? Есть свой трек?",
     "Voice and music: male, female or \"you pick\"? Got your own track?"),
)

QUESTION_KEYS = tuple(key for key, _, _ in QUESTIONS)

TITLES = {
    "language": "язык роликов",
    "platforms": "площадки",
    "sources": "откуда сырьё",
    "layout": "раскладка и верхняя панель",
    "top": "своё видео для верхней панели",
    "qr": "QR в конце",
    "brand": "стиль",
    "voice": "голос и музыка",
}

VOICES = {
    "ru": {"male": "ru-RU-DmitryNeural", "female": "ru-RU-SvetlanaNeural"},
    "en": {"male": "en-US-AndrewMultilingualNeural", "female": "en-US-AvaMultilingualNeural"},
}

DEFAULTS: Dict[str, Any] = {
    "language": "ru",
    "platforms": ["youtube_shorts", "tiktok"],
    "sources": ["site", "html", "text"],
    "qr": True,
    "brand": {"preset": "viora", "register": "minimal"},
    "voice": {"engine": "auto", "gender": "male", "speed": 1.05},
}

IMAGE_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def path(root: Optional[str] = None) -> str:
    return memory_path(FILE, root)


def template(root: Optional[str] = None) -> Dict[str, Any]:
    links = brand_links(root)
    return {
        "version": STORE_VERSION,
        "language": None,
        "platforms": None,
        "sources": None,
        "layout": None,
        "panels": {"top": {"source": None}, "bottom": {"handle": HANDLE}},
        "links": {
            "telegram": links.get("telegram"),
            "youtube": links.get("youtube"),
            "chat": links.get("chat"),
            "handle": HANDLE,
        },
        "qr": None,
        "brand": None,
        "voice": None,
        "music": {"source": None, "duck_db": -10},
        "html": {"speed": [], "sound": "page"},
        "title_style": {"chosen": [], "rejected": []},
        "history": {"styles": [], "lengths": []},
        "pending": [],
    }


def load(root: Optional[str] = None) -> Dict[str, Any]:
    data = read_json(path(root))
    if not isinstance(data, dict):
        return template(root)
    base = template(root)
    for key, value in data.items():
        base[key] = value
    return base


def save(data: Dict[str, Any], root: Optional[str] = None) -> None:
    write_json(path(root), data)


def reset(root: Optional[str] = None) -> Dict[str, Any]:
    """«Сбрось настройки»: чистый лист, ссылки снова из brand.md."""
    data = template(root)
    save(data, root)
    return data


def missing(data: Dict[str, Any]) -> List[str]:
    return [key for key in QUESTION_KEYS if data.get(key) is None and key not in data.get("pending", [])]


def questions_message(data: Dict[str, Any], lang: str = "ru") -> str:
    """Все незаданные вопросы одним сообщением, нумерованным списком."""
    keys = missing(data)
    if not keys:
        return ""
    head = ("Пара вопросов перед первым роликом, отвечай одним сообщением, можно «выбери сам»:"
            if lang == "ru" else "A few questions before the first video, one reply is enough:")
    rows = [head]
    for index, key in enumerate(keys, 1):
        text = next(ru if lang == "ru" else en for k, ru, en in QUESTIONS if k == key)
        rows.append("%d. %s" % (index, text))
    return "\n".join(rows)


def _parse_bool(value: str) -> bool:
    low = value.strip().lower()
    if low in ("1", "yes", "y", "true", "да", "ага", "on", "ставь", "нужен"):
        return True
    if low in ("0", "no", "n", "false", "нет", "off", "не надо", "не нужен"):
        return False
    raise ValueError("не понял да или нет: %s" % value)


def _custom_presets(root: Optional[str] = None) -> List[str]:
    folder = os.path.join(mod_root(root), "brand")
    try:
        return sorted(name[:-5] for name in os.listdir(folder) if name.endswith(".json"))
    except OSError:
        return []


def set_value(data: Dict[str, Any], key: str, value: str, root: Optional[str] = None) -> str:
    """Записать один ответ. Возвращает строку для автора или бросает ValueError."""
    key = key.strip().lower()
    value = value.strip()
    if key == "language":
        low = value.lower()
        code = {"русский": "ru", "рус": "ru", "russian": "ru", "английский": "en",
                "англ": "en", "english": "en"}.get(low, low)
        if len(code) < 2:
            raise ValueError("язык кодом: ru или en")
        data["language"] = code
        voice = data.get("voice")
        if isinstance(voice, dict) and voice.get("voice") and not voice["voice"].startswith(code):
            voice.pop("voice", None)
    elif key == "platforms":
        items = [item.strip().lower() for item in value.replace(";", ",").split(",") if item.strip()]
        alias = {"shorts": "youtube_shorts", "шортс": "youtube_shorts", "ютуб": "youtube",
                 "тикток": "tiktok", "рилс": "reels", "reels": "reels", "youtube": "youtube",
                 "tiktok": "tiktok", "youtube_shorts": "youtube_shorts"}
        out = []
        for item in items:
            name = alias.get(item)
            if not name:
                raise ValueError("не знаю площадку %s, есть: %s" % (item, ", ".join(PLATFORMS)))
            if name not in out:
                out.append(name)
        if not out:
            raise ValueError("площадки через запятую: youtube_shorts,tiktok")
        data["platforms"] = out
    elif key == "sources":
        items = [item.strip().lower() for item in value.split(",") if item.strip()]
        bad = [item for item in items if item not in SOURCES]
        if bad:
            raise ValueError("не знаю источник %s, есть: %s" % (", ".join(bad), ", ".join(SOURCES)))
        data["sources"] = items
    elif key == "layout":
        if value not in MODES:
            raise ValueError("раскладка одна из: %s" % ", ".join(MODES))
        data["layout"] = value
    elif key == "top":
        if value.startswith("color:"):
            raise ValueError("верхняя панель цветом это пустая панель: дай видео или html:файл.html")
        data.setdefault("panels", {}).setdefault("top", {})["source"] = value or None
        _drop_pending(data, "top")
    elif key == "qr":
        data["qr"] = _parse_bool(value)
    elif key in ("brand", "brand.preset"):
        presets = _custom_presets(root)
        if value not in presets:
            raise ValueError("стиль один из: %s" % ", ".join(presets))
        brand = data.get("brand") if isinstance(data.get("brand"), dict) else {}
        brand["preset"] = value
        brand.setdefault("register", "minimal")
        data["brand"] = brand
        data.setdefault("history", {}).setdefault("styles", []).append(value)
    elif key == "brand.register":
        if value not in ("minimal", "punch"):
            raise ValueError("регистр minimal или punch")
        brand = data.get("brand") if isinstance(data.get("brand"), dict) else dict(DEFAULTS["brand"])
        brand["register"] = value
        data["brand"] = brand
    elif key in ("voice", "voice.gender"):
        voice = data.get("voice") if isinstance(data.get("voice"), dict) else dict(DEFAULTS["voice"])
        low = value.lower()
        if low in ("male", "мужской", "муж"):
            voice["gender"] = "male"
            voice.pop("voice", None)
        elif low in ("female", "женский", "жен"):
            voice["gender"] = "female"
            voice.pop("voice", None)
        elif low in ("auto", "выбери сам", "любой"):
            voice = dict(DEFAULTS["voice"])
        else:
            voice["voice"] = value
        data["voice"] = voice
    elif key == "voice.speed":
        speed = float(value)
        if not 0.7 <= speed <= 1.4:
            raise ValueError("скорость голоса от 0.7 до 1.4")
        voice = data.get("voice") if isinstance(data.get("voice"), dict) else dict(DEFAULTS["voice"])
        voice["speed"] = speed
        data["voice"] = voice
    elif key == "music":
        data.setdefault("music", {})["source"] = value or None
    elif key.startswith("links."):
        name = key.split(".", 1)[1]
        if name != "handle" and not value.startswith("http"):
            raise ValueError("ссылка начинается с http")
        data.setdefault("links", {})[name] = value
    elif key == "html.sound":
        if value not in ("page", "mix", "sfx", "music", "mute"):
            raise ValueError("звук HTML: page, mix (страница и наши щелчки), sfx, music или mute")
        data.setdefault("html", {})["sound"] = value
    else:
        raise ValueError("не знаю настройку %s" % key)
    base = key.split(".", 1)[0]
    _drop_pending(data, base)
    return "записал: %s = %s" % (key, value)


def _drop_pending(data: Dict[str, Any], key: str) -> None:
    data["pending"] = [item for item in data.get("pending", []) if item != key]


def skip(data: Dict[str, Any], keys: Optional[List[str]] = None) -> List[str]:
    """Автор пропустил вопросы: ставим умолчания и запоминаем, что напомнить."""
    keys = keys or missing(data)
    done = []
    for key in keys:
        if key not in data.get("pending", []):
            data.setdefault("pending", []).append(key)
        done.append(key)
    return done


def effective(data: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
    """Настройки с подставленными умолчаниями: то, на чём реально строится ролик."""
    out = copy.deepcopy(data)
    for key, value in DEFAULTS.items():
        if out.get(key) is None:
            out[key] = copy.deepcopy(value)
    if lang:
        out["language"] = lang
    voice = out["voice"]
    language = out["language"] if out["language"] in VOICES else "ru"
    if not voice.get("voice"):
        voice["voice"] = VOICES[language][voice.get("gender", "male")]
    elif not voice["voice"].lower().startswith(language):
        voice["voice"] = VOICES[language][voice.get("gender", "male")]
    return out


def top_source(data: Dict[str, Any]) -> Optional[str]:
    return ((data.get("panels") or {}).get("top") or {}).get("source")


def reminder(data: Dict[str, Any], lang: str = "ru") -> str:
    """Одна строка в конец каждого ответа с роликом, пока пункт не закрыт."""
    items = list(dict.fromkeys(data.get("pending", [])))
    if not items:
        return ""
    names = [TITLES.get(item, item) for item in items]
    if lang == "ru":
        return "Не заполнено: %s. Дать сейчас?" % ", ".join(names)
    return "Not set yet: %s. Want to fill it in now?" % ", ".join(names)


def remember_title(data: Dict[str, Any], title: str, chosen: bool = True) -> None:
    box = data.setdefault("title_style", {"chosen": [], "rejected": []})
    key = "chosen" if chosen else "rejected"
    rows = box.setdefault(key, [])
    if title not in rows:
        rows.append(title)
    del rows[:-30]


def image_generator() -> Dict[str, Any]:
    """Есть ли генератор картинок. Смотрим только наличие переменных, значения не читаем вслух."""
    found = [name for name in IMAGE_KEYS if os.environ.get(name)]
    return {"available": bool(found), "keys": found}
