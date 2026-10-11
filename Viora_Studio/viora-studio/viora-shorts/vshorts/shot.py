"""Скриншоты сайтов для обложек: настоящий кадр сервиса вместо значка.

Headless Chrome без сторонних библиотек. Путь к браузеру берём из VIORA_CHROME
или ищем по известным именам, жёстких путей нет. Нет браузера или сети: None,
обложка рисуется без кадра. Защиту сайтов не обходим: страница-проверка
распознаётся по размеру и яркости и в обложку не идёт.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional

NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
WINDOWS = (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe")


def chrome() -> Optional[str]:
    env = os.environ.get("VIORA_CHROME")
    if env and os.path.exists(env):
        return env
    for name in NAMES:
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        for rel in WINDOWS:
            if base and os.path.exists(os.path.join(base, rel)):
                return os.path.join(base, rel)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


def capture(url: str, out: str, width: int = 1280, height: int = 800, wait_ms: int = 8000,
            timeout: int = 35, retries: int = 1) -> Optional[str]:
    """PNG страницы или None. Профиль браузера временный и удаляется."""
    binary = chrome()
    if not binary:
        return None
    # Свой --user-data-dir не ставим: с ним headless Chrome зависает (проверено на 154) до таймаута.
    # Режим --headless=new и так берёт временный профиль на каждый запуск.
    for _ in range(retries + 1):
        try:
            subprocess.run([binary, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            "--mute-audio", "--no-first-run",
                            "--window-size=%d,%d" % (width, height), "--virtual-time-budget=%d" % wait_ms,
                            "--screenshot=%s" % out, url],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (subprocess.SubprocessError, OSError):
            pass
        if os.path.exists(out) and os.path.getsize(out) > 5000:
            return out
    return None


def interest(path: str) -> float:
    """Годится ли кадр в герои тёмной обложки: много деталей и тёмный фон.

    Детали меряем средней силой краёв, цвет добавляет немного. Светлая страница
    (белый лист GitHub) получает штраф: на чёрной обложке VIORA она горит пятном.
    """
    from PIL import Image, ImageFilter, ImageStat

    img = Image.open(path).convert("RGB").resize((320, 200))
    gray = img.convert("L")
    detail = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    rgb = ImageStat.Stat(img).mean
    chroma = sum(abs(rgb[i] - rgb[(i + 1) % 3]) for i in range(3)) / 3
    darkness = 1 - ImageStat.Stat(gray).mean[0] / 255
    return round((detail * 2 + chroma * 0.5) * (0.3 + 0.7 * darkness), 2)


def best(urls: List[str], folder: str) -> Optional[str]:
    """Снять сайты и вернуть самый живой кадр. Отчёт о каждом кадре в shots.txt."""
    os.makedirs(folder, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor

    jobs = [(url, os.path.join(folder, "shot-%d.png" % (index + 1))) for index, url in enumerate(urls[:4])]
    with ThreadPoolExecutor(max_workers=len(jobs) or 1) as pool:
        paths = list(pool.map(lambda job: capture(*job), jobs))
    scored = [(interest(path), path, url) for (url, _), path in zip(jobs, paths) if path]
    # Тяжёлые сайты дорисовываются не сразу: бедный кадр переснимаем один раз с запасом времени.
    missing = [(url, path) for (url, path), got in zip(jobs, paths) if not got]
    for _ in range(2):
        weak = [(url, path) for score, path, url in scored if score < 10] + missing
        if not weak:
            break
        with ThreadPoolExecutor(max_workers=len(weak)) as pool:
            again = list(pool.map(lambda job: capture(job[0], job[1], wait_ms=15000, timeout=45, retries=0), weak))
        fresh = {url: (interest(path), path) for (url, _), path in zip(weak, again) if path}
        known = {url for _, _, url in scored}
        scored = [(max(score, fresh.get(url, (0, path))[0]), path, url) for score, path, url in scored]
        scored += [(score, path, url) for url, (score, path) in fresh.items() if url not in known]
        missing = [(url, path) for url, path in missing if url not in fresh]
    with open(os.path.join(folder, "shots.txt"), "w", encoding="utf-8") as handle:
        for score, path, url in sorted(scored, reverse=True):
            handle.write("%.1f %s %s\n" % (score, os.path.basename(path), url))
    scored = [row for row in scored if row[0] >= 4]
    return max(scored)[1] if scored else None
