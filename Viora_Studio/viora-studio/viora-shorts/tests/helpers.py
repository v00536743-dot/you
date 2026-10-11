"""Общее для тестов: временная копия скилла, чтобы не трогать память автора."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(TESTS)
SKILL = os.path.dirname(MOD)
FIX = os.path.join(TESTS, "fixtures")
POSTS = os.path.join(os.path.dirname(SKILL), "posts")
if MOD not in sys.path:
    sys.path.insert(0, MOD)


def temp_skill() -> str:
    """Копия viora-studio без мусора. Возвращает путь к копии."""
    base = tempfile.mkdtemp(prefix="viora-test-")
    target = os.path.join(base, "viora-studio")
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__", "out", "dist", "*.pyc", "engine"))
    os.makedirs(os.path.join(target, "viora-shorts", "engine"), exist_ok=True)
    prefs = os.path.join(target, "memory", "video-prefs.json")
    if os.path.exists(prefs):
        os.remove(prefs)
    return target


def drop(path: str) -> None:
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as handle:
        return handle.read()


def load_json(path: str):
    import json
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()
