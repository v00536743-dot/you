"""Общие мелочи модуля: пути, JSON, тире, счёт слов, ссылки автора."""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Dict, Iterable, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
SKILL = os.path.dirname(MOD)

# Правило ноль: этих символов нет нигде, включая названия и описания роликов.
DASHES = "\u2014\u2013\u2015\u2012\u2212"

# Слов в секунду у синтезатора на скорости 1.0. Замер: edge-tts DmitryNeural
# читает 100-110 слов за 40 секунд (reference/shorts.md 7.0.0), английский чуть быстрее.
WORDS_PER_SEC = {"ru": 2.6, "en": 2.8}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF]"
)
URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
HASHTAG_RE = re.compile(r"(?<![\w#])#([\w\d_]+)", re.UNICODE)
CYR_RE = re.compile("[\u0400-\u04FF]")


def skill_root(root: Optional[str] = None) -> str:
    """Каталог скилла. Тесты подменяют его временной папкой."""
    return os.path.abspath(root or os.environ.get("VIORA_SKILL_ROOT") or SKILL)


def mod_root(root: Optional[str] = None) -> str:
    return os.path.join(skill_root(root), "viora-shorts")


def memory_path(name: str, root: Optional[str] = None) -> str:
    return os.path.join(skill_root(root), "memory", name)


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def write_json(path: str, data: Any) -> None:
    """Атомарная запись: оборванный процесс не оставит полфайла настроек."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def has_dash(text: str) -> bool:
    return any(ch in (text or "") for ch in DASHES)


def fix_dashes(text: str) -> str:
    """Длинное тире в окружении пробелов становится дефисом, прочие тоже."""
    out = text or ""
    for ch in DASHES:
        out = out.replace(" %s " % ch, " - ").replace(ch, "-")
    return out


def walk_strings(data: Any) -> Iterable[str]:
    """Все строки внутри JSON-структуры: для сквозной проверки тире."""
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for key, value in data.items():
            yield str(key)
            yield from walk_strings(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk_strings(value)


def words(text: str) -> List[str]:
    return re.findall(r"[\w\d][\w\d'+.-]*", text or "", re.UNICODE)


def speech_seconds(text: str, lang: str = "ru", speed: float = 1.0) -> float:
    rate = WORDS_PER_SEC.get(lang, 2.6) * max(speed, 0.1)
    return len(words(text)) / rate


def emojis(text: str) -> List[str]:
    return EMOJI_RE.findall(text or "")


def hashtags(text: str) -> List[str]:
    return ["#" + tag for tag in HASHTAG_RE.findall(text or "")]


def is_cyrillic(text: str) -> bool:
    return bool(CYR_RE.search(text or ""))


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o",
     "p", "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


def slug(text: str, limit: int = 40) -> str:
    """Имя ролика по схеме: ^[a-z0-9][a-z0-9-]*$."""
    low = (text or "").lower()
    out = "".join(_TRANSLIT.get(ch, ch) for ch in low)
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    out = out[:limit].strip("-")
    return out or "reel"


def brand_links(root: Optional[str] = None) -> Dict[str, str]:
    """Ссылки автора из reference/brand.md. Источник один, ничего не выдумываем."""
    path = os.path.join(skill_root(root), "reference", "brand.md")
    found: Dict[str, str] = {}
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return found
    keys = (("канал", "telegram"), ("чат", "chat"), ("github", "github"),
            ("youtube", "youtube"), ("визитк", "site"))
    for line in text.splitlines():
        if not line.startswith("|") or "http" not in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        label = cells[0].lower()
        url = URL_RE.search(cells[1])
        if not url:
            continue
        for word, key in keys:
            if word in label and key not in found:
                found[key] = url.group(0)
    return found


def short_link(url: str) -> str:
    """t.me/VioraStudio вместо https://t.me/VioraStudio: так читают с экрана."""
    return re.sub(r"^https?://(www\.)?", "", (url or "").rstrip("/"))
