"""Адаптер html: один HTML-файл (игра, анимация, «фильм») превращается в сцены плана.

Два способа снять страницу (COMMON.md раздел 10):
- deterministic: виртуальное время, кадр за кадром. Идеально гладко, но звук
  страницы так не записать: вместо него SFX и музыка. Берём, если у страницы есть
  window.__seek(t) или в ней нет своего звука.
- realtime: запись в реальном времени вместе со звуком страницы, потом ретайм
  по карте скоростей (видео через setpts, звук через atempo). Берём, когда автор
  хочет слышать звук самой страницы.

Код только читает файл и раскладывает таймлайн. Снимает движок.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

SOUNDS = ("page", "sfx", "music", "mute")


@dataclass
class Chapter:
    title: str
    start: float
    end: float
    best: bool = False


@dataclass
class HtmlInfo:
    path: str
    title: str = ""
    size_kb: int = 0
    has_canvas: bool = False
    has_three: bool = False
    has_webaudio: bool = False
    has_media: bool = False
    seek_hook: bool = False
    needs_click: bool = False
    needs_network: bool = False
    duration: float = 0.0
    keys: List[str] = field(default_factory=list)
    chapters: List[Chapter] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    def facts_text(self) -> str:
        """Факты для проверки цифр в сценарии: всё, что код честно узнал из файла."""
        return "%s %d КБ %d секунд %d глав" % (self.title, self.size_kb, round(self.duration), len(self.chapters))


KEY_RE = re.compile(r"""(?:e|event|evt|ev)\.(?:key|code)\s*===?\s*['"]([^'"]{1,12})['"]""")
DURATION_RE = re.compile(r"""(?:__duration\s*=\s*|data-duration\s*=\s*['"]?)(\d+(?:\.\d+)?)""")
SCENE_RE = re.compile(
    r"""<[^>]*data-scene\s*=\s*['"]([^'"]+)['"][^>]*>""", re.I)
ATTR_RE = re.compile(r"""data-(t|end|best)\s*=\s*['"]?([\w.]+)""", re.I)


def inspect(path: str) -> HtmlInfo:
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    low = text.lower()
    info = HtmlInfo(path=os.path.abspath(path))
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    info.title = " ".join(match.group(1).split()) if match else os.path.basename(path)
    info.size_kb = max(1, round(os.path.getsize(path) / 1024))
    info.has_canvas = "<canvas" in low or "getcontext(" in low
    info.has_three = "three.module" in low or "three.min.js" in low or "new three." in low or "from 'three'" in low \
        or 'from "three"' in low
    info.has_webaudio = "audiocontext" in low
    info.has_media = "<audio" in low or "<video" in low or "new audio(" in low
    info.seek_hook = "__seek" in text
    info.needs_click = bool(re.search(r"(click|tap|нажми|кликни)[^<]{0,30}(start|начать|play|старт)", low)) \
        or (info.has_webaudio and "resume()" in low)
    info.needs_network = bool(re.search(r"""<script[^>]+src\s*=\s*['"]https?://""", low)) or \
        bool(re.search(r"""import[^;]+from\s*['"]https?://""", low))
    found = DURATION_RE.search(text)
    info.duration = float(found.group(1)) if found else 0.0
    info.keys = sorted(set(KEY_RE.findall(text)))[:12]
    chapters: List[Chapter] = []
    for tag in SCENE_RE.finditer(text):
        attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag.group(0))}
        start = float(attrs["t"]) if "t" in attrs else -1.0
        chapters.append(Chapter(tag.group(1).strip(), start, float(attrs.get("end", -1)),
                                attrs.get("best", "").lower() in ("1", "true", "yes")))
    info.chapters = _fill_times(chapters, info.duration)
    return info


def _fill_times(chapters: List[Chapter], duration: float) -> List[Chapter]:
    if not chapters:
        return []
    if duration <= 0:
        known = [c.end for c in chapters if c.end > 0] + [c.start for c in chapters if c.start >= 0]
        duration = max(known) if known else 6.0 * len(chapters)
    step = duration / len(chapters)
    for index, chapter in enumerate(chapters):
        if chapter.start < 0:
            chapter.start = round(index * step, 2)
    for index, chapter in enumerate(chapters):
        if chapter.end <= chapter.start:
            nxt = chapters[index + 1].start if index + 1 < len(chapters) else duration
            chapter.end = round(nxt, 2)
    return chapters


def parse_speed(spec: str) -> List[Dict[str, float]]:
    """«0-5:1,5-12:2.5,12-15:0.5» -> [{t:0, rate:1}, {t:5, rate:2.5}, {t:12, rate:0.5}]."""
    out: List[Dict[str, float]] = []
    if not spec:
        return out
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        span, _, rate = chunk.partition(":")
        start = float(span.split("-")[0])
        value = float(rate)
        if not 0.25 <= value <= 4.0:
            raise ValueError("скорость %s вне 0.25-4: медленнее рвётся звук, быстрее не видно" % value)
        out.append({"t": start, "rate": value})
    out.sort(key=lambda row: row["t"])
    return out


def output_length(start: float, end: float, speed: List[Dict[str, float]]) -> float:
    """Сколько секунд кусок исходника займёт в ролике после карты скоростей."""
    if end <= start:
        return 0.0
    marks = sorted(speed, key=lambda row: row["t"])
    cuts = sorted({start, end} | {row["t"] for row in marks if start < row["t"] < end})
    total = 0.0
    for left, right in zip(cuts, cuts[1:]):
        # До первой метки скорость 1.0, дальше действует последняя метка слева.
        rate = 1.0
        for row in marks:
            if row["t"] <= left:
                rate = row["rate"]
        total += (right - left) / rate
    return round(total, 2)


def capture_mode(info: HtmlInfo, sound: str) -> str:
    if sound == "page" and (info.has_webaudio or info.has_media):
        return "realtime"
    return "deterministic"


def capture_action(info: HtmlInfo, sound: str, start: float, end: float, fps: int = 30) -> Dict[str, Any]:
    """Действие capture для движка. Поля сверх схемы описаны в CONTRACT-ISSUES.md."""
    mode = capture_mode(info, sound)
    action: Dict[str, Any] = {
        "do": "capture", "mode": mode, "from": round(start, 2), "to": round(end, 2), "fps": fps,
        "sound": sound if (sound != "page" or mode == "realtime") else "sfx",
        "seek_hook": info.seek_hook,
    }
    if info.needs_click:
        action["start_click"] = True
    if mode == "realtime":
        action["autoplay_policy"] = "no-user-gesture-required"
    return action


def demo_inputs(info: HtmlInfo, start: float, end: float) -> List[Dict[str, Any]]:
    """Для игры: короткие нажатия клавиш, чтобы в кадре было движение каждые 2-3 с."""
    if not info.keys:
        return []
    out: List[Dict[str, Any]] = []
    t = 0.8
    index = 0
    while start + t < end - 0.5 and len(out) < 8:
        out.append({"t": round(t, 2), "do": "key", "key": info.keys[index % len(info.keys)], "hold": 0.6})
        t += 2.2
        index += 1
    return out


def best_window(info: HtmlInfo, seconds: float = 3.0) -> Tuple[float, float]:
    """Самый зрелищный кусок для первой секунды: глава с data-best или середина."""
    best = next((c for c in info.chapters if c.best), None)
    if best:
        return best.start, min(best.end, best.start + seconds)
    middle = (info.duration or 6.0) / 2
    return round(middle, 2), round(middle + seconds, 2)
