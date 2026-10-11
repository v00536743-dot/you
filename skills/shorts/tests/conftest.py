"""Shared fixtures. Every test runs with its own memory and cache folders (no network unless marked)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
FIX = ROOT / "tests" / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet (sites, YouTube, TTS service); skipped unless SHORTS_NETWORK=1")
    config.addinivalue_line("markers", "slow: renders a full video")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SHORTS_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="network test (set SHORTS_NETWORK=1)")
    for it in items:
        if "network" in it.keywords:
            it.add_marker(skip)


@pytest.fixture(scope="session")
def session_dirs(tmp_path_factory):
    base = tmp_path_factory.mktemp("shorts")
    cache = base / "cache"
    tts = cache / "tts"
    tts.mkdir(parents=True)
    # ready-made voice for the offline plan ("готовая озвучка"): ogg in git -> wav in the cache
    for ogg in (FIX / "tts").glob("*.ogg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ogg), "-ar", "48000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(tts / (ogg.stem + ".wav"))], check=True)
        shutil.copy(ogg.with_suffix(".json"), tts / (ogg.stem + ".json"))
    return base


@pytest.fixture(autouse=True)
def isolated_env(session_dirs, tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTS_CACHE", str(session_dirs / "cache"))
    monkeypatch.setenv("SHORTS_MEMORY", str(tmp_path / "memory"))
    if os.environ.get("SHORTS_NETWORK") != "1":
        monkeypatch.setenv("SHORTS_IMAGE_PROVIDER", "none")
    yield


def write_plan(tmp: Path, plan: dict, name: str = "plan.json") -> Path:
    for f in ("orbit.html", "app-screen.png"):
        if not (tmp / f).exists():
            shutil.copy(FIX / f, tmp / f)
    p = tmp / name
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def mini_plan(**over) -> dict:
    """6-second plan without TTS (fast). Captions come from a given transcript."""
    plan = {
        "schema_version": "1",
        "meta": {"name": "mini", "language": "ru", "platforms": ["youtube_shorts"], "duration_target": [4, 12], "loop": True},
        "layout": {"mode": "center_only", "cta_in_center": []},
        "brand": {"preset": "viora"},
        "captions": {"enabled": True, "max_words": 3},
        "audio": {"music": {"source": "assets/audio/bed.mp3"}, "sfx_auto": False},
        "scenes": [{
            "id": "a", "why": "test", "duration": 6.0, "on_screen_text": "ТЕСТ КАДРА",
            "source": {"type": "html", "ref": "orbit.html"},
            "transcript": [{"w": "Два", "s": 0.2, "e": 0.5}, {"w": "бесплатных", "s": 0.55, "e": 1.1},
                           {"w": "сайта,", "s": 1.15, "e": 1.6}, {"w": "и", "s": 1.9, "e": 2.0},
                           {"w": "оба", "s": 2.05, "e": 2.4}, {"w": "пригодятся.", "s": 2.45, "e": 3.2},
                           {"w": "Смотри", "s": 3.6, "e": 4.0}, {"w": "до", "s": 4.05, "e": 4.2},
                           {"w": "конца.", "s": 4.25, "e": 4.8}]}],
    }
    for k, v in over.items():
        plan[k] = v
    return plan
