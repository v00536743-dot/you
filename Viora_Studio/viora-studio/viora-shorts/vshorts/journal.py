"""Журнал роликов, замеры через 24 часа и 7 дней, эксперименты по одной переменной.

Файлы: memory/video-log.md (что вышло и когда мерить), раздел «Шортсы: замеры»
в memory/metrics.md (цифры), memory/experiments.md (что меняли и что вышло).
Правила замера: research/click-and-watch.md раздел 10.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Dict, List, Optional

from .common import memory_path

LOG = "video-log.md"
EXPERIMENTS = "experiments.md"
METRICS = "metrics.md"
SECTION = "## Шортсы: замеры"
LOG_HEADER = "| Дата | Ролик | Название | Площадки | Длина, с | Замер 24ч | Замер 7д |"
LOG_RULE = "|---|---|---|---|---|---|---|"
METRIC_HEADER = ("| Дата | Ролик | Окно | Показано в ленте | Остались, % | Средний % просмотра "
                 "| Лайки | Подписки | Переходы |")
METRIC_RULE = "|---|---|---|---|---|---|---|---|---|"
WAIT = "ждёт"
DONE = "снят"


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def log_template() -> str:
    return ("# Журнал роликов\n\n"
            "Что вышло и когда снимать цифры. Строку пишет `reel.py log`, замер ставит `reel.py measure`.\n"
            "Даты замера: через сутки и через неделю после выхода. Сравниваем с медианой своих\n"
            "последних 10 роликов, а не с «нормой интернета».\n\n"
            "%s\n%s\n" % (LOG_HEADER, LOG_RULE))


def add(name: str, title: str, platforms: List[str], seconds: float, date: Optional[str] = None,
        root: Optional[str] = None) -> Dict[str, str]:
    day = date or dt.date.today().isoformat()
    base = dt.date.fromisoformat(day)
    h24 = (base + dt.timedelta(days=1)).isoformat()
    d7 = (base + dt.timedelta(days=7)).isoformat()
    title = title.replace("|", "/")
    row = "| %s | %s | %s | %s | %.0f | %s %s | %s %s |" % (
        day, name, title, ", ".join(platforms), seconds, WAIT, h24, WAIT, d7)
    path = memory_path(LOG, root)
    text = _read(path) or log_template()
    if ("| %s |" % name) in text:
        return {"row": "", "note": "ролик %s уже в журнале" % name}
    _write(path, text.rstrip("\n") + "\n" + row + "\n")
    return {"row": row, "h24": h24, "d7": d7}


def _rows(text: str) -> List[List[str]]:
    out = []
    for line in text.splitlines():
        if line.startswith("| 20"):
            out.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return out


def due(today: Optional[str] = None, root: Optional[str] = None) -> List[Dict[str, str]]:
    """Какие замеры пора снять. Пропущенный замер тоже попадает сюда, пока не снят."""
    now = dt.date.fromisoformat(today) if today else dt.date.today()
    out = []
    for cells in _rows(_read(memory_path(LOG, root))):
        for window, cell in (("24h", cells[5]), ("7d", cells[6])):
            match = re.match(r"%s (\d{4}-\d{2}-\d{2})" % WAIT, cell)
            if match and dt.date.fromisoformat(match.group(1)) <= now:
                out.append({"name": cells[1], "window": window, "date": match.group(1), "title": cells[2]})
    return out


def measure(name: str, window: str, values: Dict[str, Any], date: Optional[str] = None,
            root: Optional[str] = None) -> str:
    if window not in ("24h", "7d"):
        raise ValueError("окно замера 24h или 7d")
    day = date or dt.date.today().isoformat()
    path = memory_path(LOG, root)
    lines = _read(path).splitlines()
    col = 5 if window == "24h" else 6
    hit = False
    for index, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| 20") and len(cells) >= 7 and cells[1] == name:
            cells[col] = "%s %s" % (DONE, day)
            lines[index] = "| " + " | ".join(cells) + " |"
            hit = True
    if not hit:
        raise ValueError("ролика %s нет в журнале" % name)
    _write(path, "\n".join(lines) + "\n")
    keys = ("shown", "viewed_pct", "avg_pct", "likes", "subs", "clicks")
    row = "| %s | %s | %s | %s |" % (day, name, window, " | ".join(str(values.get(k, "-")) for k in keys))
    mpath = memory_path(METRICS, root)
    text = _read(mpath) or "# Метрики канала\n"
    if SECTION not in text:
        text = text.rstrip("\n") + "\n\n%s\n\nПишет `reel.py measure`. Остались, % это viewed vs swiped away из Studio.\n\n%s\n%s\n" % (
            SECTION, METRIC_HEADER, METRIC_RULE)
    head, _, tail = text.partition(SECTION)
    block, sep, rest = tail.partition("\n## ")
    block = block.rstrip("\n") + "\n" + row + "\n"
    text = head + SECTION + block + (("\n## " + rest) if sep else "")
    _write(mpath, text)
    return row


def suggest(values: Dict[str, Any], median: Optional[Dict[str, float]] = None) -> str:
    """Следующий эксперимент по разделу 10 исследования. Меняем ОДНУ вещь за раз."""
    median = median or {}
    def num(key: str) -> Optional[float]:
        try:
            return float(values.get(key))
        except (TypeError, ValueError):
            return None
    shown, viewed, avg, subs = num("shown"), num("viewed_pct"), num("avg_pct"), num("subs")
    if shown is not None and median.get("shown") and shown < 0.5 * median["shown"]:
        return "мало показов: меняем тему или название, остальное оставляем"
    if viewed is not None and viewed < median.get("viewed_pct", 60):
        return "смахивают в первую секунду: меняем только первый кадр и первую фразу"
    if avg is not None and avg < median.get("avg_pct", 70):
        return "смотрят начало, но уходят: режем середину, новое событие каждые 2 секунды"
    if subs is not None and subs <= median.get("subs", 0):
        return "смотрят, но не подписываются: усиливаем призыв и причину (часть 2), проверяем профиль"
    return "всё держится: повторяем формат и меняем одну деталь, например обложку"


def experiments_template() -> str:
    return ("# Эксперименты с роликами\n\n"
            "Правило: за раз меняем ОДНУ вещь (первый кадр, первая фраза, название, обложка, длина)\n"
            "и держим её на следующих трёх роликах. Источник: research/click-and-watch.md раздел 10.\n\n"
            "| Дата | Что меняем | Гипотеза | Ролики | Результат | Следующий шаг |\n"
            "|---|---|---|---|---|---|\n")


def add_experiment(change: str, hypothesis: str, reels: str = "-", date: Optional[str] = None,
                   root: Optional[str] = None) -> str:
    day = date or dt.date.today().isoformat()
    row = "| %s | %s | %s | %s | ждём замер | - |" % (day, change.replace("|", "/"),
                                                      hypothesis.replace("|", "/"), reels)
    path = memory_path(EXPERIMENTS, root)
    text = _read(path) or experiments_template()
    _write(path, text.rstrip("\n") + "\n" + row + "\n")
    return row
