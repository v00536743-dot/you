"""Связь с движком SHORTS: найти, отдать план, получить ролик и отчёт QA.

Интерфейс движка из PROMPT-1-SHORTS.md:
    python3 <engine>/tools/shorts.py render plan.json --out DIR
    python3 <engine>/tools/shorts.py qa DIR
Что мы ждём в DIR после рендера, записано в viora-v8/spec/CONTRACT-ISSUES.md:
*.mp4, qa.json (passed, checks), words.json (тайминги слов), contact.png.
Чего нет, то честно помечаем в отчёте как «не проверено».
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from .common import mod_root, read_json

ENV = "VIORA_SHORTS_ENGINE"


def find(root: Optional[str] = None, override: Optional[str] = None) -> Optional[List[str]]:
    """Команда запуска движка или None. override: путь к shorts.py, папке движка или 'fake'."""
    candidates: List[str] = []
    if override == "fake":
        return [sys.executable, os.path.join(mod_root(root), "tests", "fake_engine.py")]
    for value in (override, os.environ.get(ENV)):
        if value:
            candidates += [value, os.path.join(value, "tools", "shorts.py"), os.path.join(value, "shorts.py")]
    base = os.path.join(mod_root(root), "engine")
    candidates += [os.path.join(base, "tools", "shorts.py"), os.path.join(base, "shorts.py")]
    for path in candidates:
        if path and os.path.isfile(path) and path.endswith(".py"):
            return [sys.executable, os.path.abspath(path)]
    return None


def version(root: Optional[str] = None) -> str:
    try:
        return open(os.path.join(mod_root(root), "ENGINE_VERSION"), encoding="utf-8").read().strip()
    except OSError:
        return "движок не вшит"


def _run(cmd: List[str], timeout: int) -> Dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"code": proc.returncode, "out": proc.stdout[-4000:], "err": proc.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        return {"code": 124, "out": "", "err": "движок не уложился в %d с" % timeout}
    except OSError as error:
        return {"code": 127, "out": "", "err": str(error)}


def collect(out_dir: str) -> Dict[str, Any]:
    videos = sorted(glob.glob(os.path.join(out_dir, "*.mp4")))
    qa = read_json(os.path.join(out_dir, "qa.json"))
    return {
        "video": videos[0] if videos else None,
        "qa": qa,
        "words": read_json(os.path.join(out_dir, "words.json")),
        "contact": next((p for p in (os.path.join(out_dir, "contact.png"), os.path.join(out_dir, "contact.jpg"))
                         if os.path.exists(p)), None),
        "result": read_json(os.path.join(out_dir, "result.json")),
    }


def render(cmd: List[str], plan_path: str, out_dir: str, timeout: int = 1800) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    step = _run(cmd + ["render", plan_path, "--out", out_dir], timeout)
    step.update(collect(out_dir))
    return step


def qa(cmd: List[str], out_dir: str, timeout: int = 600) -> Dict[str, Any]:
    step = _run(cmd + ["qa", out_dir], timeout)
    data = read_json(os.path.join(out_dir, "qa.json"))
    if data is None:
        try:
            data = json.loads(step["out"])
        except (ValueError, TypeError):
            data = {"passed": step["code"] == 0, "checks": [], "note": "движок не дал qa.json, судим по коду выхода"}
    step["report"] = data
    step["passed"] = bool(data.get("passed")) and step["code"] == 0
    return step


def failed_checks(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in (report or {}).get("checks", []) if not c.get("ok", c.get("passed", False))]
