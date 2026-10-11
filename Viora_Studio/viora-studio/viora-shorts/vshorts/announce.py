"""Анонс ролика в канал по рубрике #шортс (reference/formats.md).

Анонс всегда на русском: канал русский, даже если ролик английский.
Текст гоняется через lint_post.py --strict той же рубрикой, без чистого
линтера автору не отдаётся (правило 7.0.0).
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List, Optional

from .common import plural_ru, skill_root

FOOTER = ("[ЧАТ](https://t.me/viorames) | [GITHUB](https://github.com/badVIno-ctrl) | "
          "[YOUTUBE](https://www.youtube.com/@badVIno-VS) | [ТГК](https://t.me/VioraStudio)")
STUDY = {"Linux": "Linux", "3D": "3D", "Майнкрафта": "Майнкрафт", "нейросетей": "нейросети",
         "дизайна": "дизайн", "кода": "код", "веба": "веб"}


def _tool(name: str, root: Optional[str] = None) -> Any:
    path = os.path.join(skill_root(root), "tools", "%s.py" % name)
    spec = importlib.util.spec_from_file_location("viora_%s" % name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def greetings(root: Optional[str] = None) -> List[str]:
    """Свежие приветствия из банка канала: занятые и банальные отброшены."""
    try:
        data = _tool("memory", root).greet(skill_root(root), rubric="шортс")
        return [item["text"] for item in data.get("items") or []]
    except Exception:  # память канала недоступна: анонс без приветствия тоже валиден
        return []


def greeting(root: Optional[str] = None) -> str:
    found = greetings(root)
    return found[0] if found else ""


def best(facts: Dict[str, Any], seconds: float, video_url: str, dropped: Optional[List[str]] = None,
         root: Optional[str] = None) -> Any:
    """Первый вариант анонса с чистым строгим линтером. Чистого нет: лучший и его замечания."""
    tried = []
    for hello in greetings(root) + [""]:
        text = build(facts, seconds, video_url, dropped, root, hello=hello)
        issues = lint(text, root)
        if not issues:
            return text, []
        tried.append((len(issues), text, issues))
    tried.sort(key=lambda row: row[0])
    return tried[0][1], tried[0][2]


def build(facts: Dict[str, Any], seconds: float, video_url: str, dropped: Optional[List[str]] = None,
          root: Optional[str] = None, hello: Optional[str] = None) -> str:
    n = facts["count"]
    names = [name for name in facts.get("names_ru", facts["names"])]
    listing = ", ".join(names[:-1]) + " и " + names[-1] if len(names) > 1 else names[0]
    noun = facts.get("noun", "сайт")
    if noun == "находка":
        what = plural_ru(n, "бесплатная находка", "бесплатные находки", "бесплатных находок")
    else:
        what = plural_ru(n, "бесплатный сайт", "бесплатных сайта", "бесплатных сайтов")
    secs = int(round(seconds))
    rows: List[str] = []
    hello = greeting(root) if hello is None else hello
    if hello:
        rows += [hello, ""]
    rows.append("%d %s за %d %s: %s. Всё показал вживую, без воды)" %
                (n, what, secs, plural_ru(secs, "секунду", "секунды", "секунд"), listing))
    rows.append("")
    if dropped:
        rows.append("%s в ролик не %s: закрыт от записи, ссылка в посте про находки." %
                    (", ".join(dropped), "влез" if len(dropped) == 1 else "влезли"))
    else:
        rows.append("Ссылки на все сайты в закрепе под видео, там же короткая инструкция.")
    rows += ["", "[ВИДЕО](%s)" % video_url, ""]
    study = [STUDY[l] for l in facts.get("labels_ru", facts.get("labels", [])) if l in STUDY][:2]
    if study:
        rows.append("Перешли тому, кто сейчас учит %s." % " или ".join(study))
    else:
        rows.append("Перешли тому, кому это сэкономит вечер.")
    rows += ["#шортс", "", FOOTER]
    return "\n".join(rows) + "\n"


def lint(text: str, root: Optional[str] = None) -> List[Dict[str, str]]:
    module = _tool("lint_post", root)
    issues, _ = module.lint(text, rubric="шортс")
    errors, warns = module.split_levels(issues, strict=True)
    return errors + warns
