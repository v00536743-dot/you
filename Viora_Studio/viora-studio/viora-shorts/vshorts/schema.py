"""Проверка плана: JSON Schema (подмножество draft 2020-12) плюс правила Viora.

Свой валидатор, чтобы скилл работал без pip. Если установлен jsonschema,
тесты сверяют наш ответ с ним на тех же планах.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from .common import has_dash, is_cyrillic, mod_root, read_json, walk_strings

TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_schema(root: Optional[str] = None) -> Dict[str, Any]:
    """Схема движка, если он вшит, иначе копия контракта из viora-shorts/contract."""
    base = mod_root(root)
    for rel in (("engine", "spec", "plan.schema.json"), ("contract", "plan.schema.json")):
        data = read_json(os.path.join(base, *rel))
        if data:
            return data
    raise FileNotFoundError("нет plan.schema.json ни в engine/spec, ни в contract/")


def _is_type(value: Any, name: str) -> bool:
    if name in ("number", "integer") and isinstance(value, bool):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, TYPES[name])


def validate(value: Any, schema: Dict[str, Any], where: str = "$") -> List[str]:
    """Ошибки в виде «путь: что не так». Пустой список значит план по схеме."""
    out: List[str] = []
    kind = schema.get("type")
    if kind:
        names = kind if isinstance(kind, list) else [kind]
        if not any(_is_type(value, name) for name in names):
            return ["%s: ждали тип %s" % (where, "/".join(names))]
    if "const" in schema and value != schema["const"]:
        out.append("%s: должно быть %r" % (where, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        out.append("%s: %r не из списка %s" % (where, value, schema["enum"]))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append("%s: строка короче %d" % (where, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append("%s: строка длиннее %d" % (where, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append("%s: не подходит под шаблон %s" % (where, schema["pattern"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append("%s: меньше %s" % (where, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            out.append("%s: больше %s" % (where, schema["maximum"]))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append("%s: должно быть больше %s" % (where, schema["exclusiveMinimum"]))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            out.append("%s: должно быть меньше %s" % (where, schema["exclusiveMaximum"]))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append("%s: элементов меньше %d" % (where, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append("%s: элементов больше %d" % (where, schema["maxItems"]))
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                out.extend(validate(item, schema["items"], "%s[%d]" % (where, index)))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append("%s: нет обязательного поля %s" % (where, key))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            path = "%s.%s" % (where, key)
            if key in props:
                out.extend(validate(item, props[key], path))
            elif extra is False:
                out.append("%s: лишнее поле" % path)
            elif isinstance(extra, dict):
                out.extend(validate(item, extra, path))
    return out


def plan_duration(plan: Dict[str, Any]) -> float:
    """Оценка длины по подсказкам сцен. Настоящую длину знает только движок после озвучки."""
    return round(sum(float(s.get("x_duration_hint", 0) or 0) for s in plan.get("scenes", [])), 2)


def check_rules(plan: Dict[str, Any], expect_qr_url: Optional[str] = None,
                known_presets: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Правила COMMON.md, которые видны прямо в плане, до рендера."""
    issues: List[Dict[str, str]] = []

    def add(level: str, code: str, msg: str) -> None:
        issues.append({"level": level, "code": code, "message": msg})

    layout = plan.get("layout", {})
    mode = layout.get("mode")
    top = layout.get("top") or {}
    bottom = layout.get("bottom") or {}
    has_top = mode in ("three", "top_center")
    has_bottom = mode in ("three", "center_bottom")
    used = (float(top.get("height_pct", 20)) if has_top else 0.0) + \
           (float(bottom.get("height_pct", 20)) if has_bottom else 0.0)
    if 100 - used < 55:
        add("ERROR", "E-CENTER", "центр %.0f%% высоты, нужно не меньше 55%%" % (100 - used))
    if has_top and not top.get("source"):
        add("ERROR", "E-TOP-EMPTY", "верхняя панель без видео: пустая панель хуже, чем её отсутствие")
    if has_top and re.search(r"(ball|шар|gradient|градиент)", str(top.get("source", "")), re.I):
        add("ERROR", "E-TOP-SLOP", "в верхней панели абстрактный фон, нужен живой кадр")
    if not has_top and top:
        add("WARN", "W-TOP-IGNORED", "раскладка %s без верха, а top задан" % mode)

    duration = plan_duration(plan)
    ctas = layout.get("cta_in_center", [])
    if len(ctas) > 3:
        add("ERROR", "E-CTA-MANY", "вспышек %d, максимум три" % len(ctas))
    spans = []
    for flash in ctas:
        t = float(flash.get("t", 0))
        d = float(flash.get("duration", 2.5))
        if not 1.5 <= d <= 3.0:
            add("ERROR", "E-CTA-LEN", "вспышка %s длится %.1f с, нужно 1.5-3" % (flash.get("kind"), d))
        if flash.get("kind") in ("handle", "qr") and not (flash.get("text") or flash.get("url")):
            add("ERROR", "E-CTA-TEXT", "вспышка %s без текста ссылки" % flash.get("kind"))
        spans.append((t, t + d, flash.get("kind")))
        if duration and t + d > duration + 0.05:
            add("ERROR", "E-CTA-PAST-END", "вспышка %s выходит за конец ролика" % flash.get("kind"))
    spans.sort()
    for (a0, a1, ak), (b0, b1, bk) in zip(spans, spans[1:]):
        if b0 < a1 - 0.01:
            add("ERROR", "E-CTA-OVERLAP", "вспышки %s и %s наложились" % (ak, bk))
    qr = [f for f in ctas if f.get("kind") == "qr"]
    if expect_qr_url is not None:
        if not qr:
            add("ERROR", "E-QR-MISSING", "QR включён в настройках, а вспышки с QR нет")
        for flash in qr:
            if flash.get("url") != expect_qr_url:
                add("ERROR", "E-QR-URL", "QR ведёт на %s, ждали %s" % (flash.get("url"), expect_qr_url))
            if not flash.get("text"):
                add("ERROR", "E-QR-NO-TEXT", "рядом с QR нет текстовой ссылки: с экрана телефона его не отсканировать")
    for flash in qr:
        if duration and not duration - 4.05 <= float(flash["t"]) <= duration - 2.95:
            add("WARN", "W-QR-WHEN", "QR не в последних 3-4 секундах (t=%.1f из %.1f)" % (flash["t"], duration))
    for flash in ctas:
        if flash.get("kind") == "handle" and duration:
            share = float(flash["t"]) / duration
            if not 0.35 <= share <= 0.65:
                add("WARN", "W-HANDLE-WHEN", "ник на %.0f%% ролика, лучше 40-60%% после первой пользы" % (share * 100))

    brand = plan.get("brand", {})
    preset = brand.get("preset")
    if known_presets and preset not in known_presets:
        add("ERROR", "E-BRAND", "неизвестный пресет %s" % preset)
    palette = brand.get("palette") or {}
    colors = {str(v).upper() for v in palette.values()}
    if len(colors) > 3:
        add("ERROR", "E-COLORS", "в палитре больше трёх цветов")
    for name, value in palette.items():
        if not HEX.match(str(value)):
            add("ERROR", "E-COLOR-HEX", "цвет %s=%s не в формате #RRGGBB" % (name, value))
    if preset == "mono":
        for value in colors:
            if HEX.match(value) and not value[1:3] == value[3:5] == value[5:7]:
                add("ERROR", "E-MONO-COLOR", "в mono цвет %s не серый" % value)
    fonts = brand.get("fonts") or {}
    for role, font in fonts.items():
        if re.search(r"(dejavu|arial|helvetica|liberation|times)", str(font), re.I):
            add("ERROR", "E-FONT-DEFAULT", "шрифт %s по умолчанию: берём шрифт бренда" % role)

    captions = plan.get("captions", {})
    if captions.get("enabled") is False:
        add("WARN", "W-CAPTIONS-OFF", "субтитры выключены: ролик смотрят без звука")
    if captions.get("max_words", 3) > 3:
        add("ERROR", "E-CAPTION-WORDS", "в порции субтитров больше трёх слов")

    audio = plan.get("audio", {})
    if "target_lufs" in audio and abs(float(audio["target_lufs"]) + 14) > 1.5:
        add("ERROR", "E-LUFS", "громкость %.1f LUFS, нужно около -14" % audio["target_lufs"])

    ids = [s.get("id") for s in plan.get("scenes", [])]
    if len(ids) != len(set(ids)):
        add("ERROR", "E-SCENE-ID", "у сцен повторяются id")
    language = plan.get("meta", {}).get("language", "ru")
    for scene in plan.get("scenes", []):
        if not scene.get("why"):
            add("WARN", "W-WHY", "сцена %s без поля why: зачем она в ролике?" % scene.get("id"))
        if language == "en" and is_cyrillic(scene.get("say", "") + scene.get("on_screen_text", "")):
            add("ERROR", "E-LANG", "сцена %s: английский ролик, а текст русский" % scene.get("id"))
        times = [float(a.get("t", 0)) for a in scene.get("source", {}).get("actions", []) if "t" in a]
        hint = float(scene.get("x_duration_hint", 0) or 0)
        if hint and scene.get("source", {}).get("type") == "site":
            marks = sorted(set([0.0] + times + [hint]))
            gap = max((b - a for a, b in zip(marks, marks[1:])), default=0)
            if gap > 3.05:
                add("WARN", "W-STILL", "сцена %s: %.1f с без нового события, нужно каждые 2-3 с" % (scene.get("id"), gap))

    target = plan.get("meta", {}).get("duration_target")
    if target and duration:
        if duration > target[1] + 0.05:
            add("ERROR", "E-DURATION", "оценка %.1f с длиннее цели %s" % (duration, target))
        elif duration < target[0] - 0.05:
            add("WARN", "W-DURATION", "оценка %.1f с короче цели %s" % (duration, target))

    if any(has_dash(text) for text in walk_strings(plan)):
        add("ERROR", "E-DASH", "в плане есть длинное тире")
    return issues


def full_check(plan: Dict[str, Any], schema: Optional[Dict[str, Any]] = None,
               expect_qr_url: Optional[str] = None, known_presets: Optional[List[str]] = None,
               root: Optional[str] = None) -> List[Dict[str, str]]:
    schema = schema or load_schema(root)
    issues = [{"level": "ERROR", "code": "E-SCHEMA", "message": msg} for msg in validate(plan, schema)]
    return issues + check_rules(plan, expect_qr_url, known_presets)
