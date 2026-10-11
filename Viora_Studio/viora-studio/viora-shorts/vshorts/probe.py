"""Проверка, что сайт открывается, и выбор лучших пунктов под ролик.

Защиту от ботов НЕ обходим. Страница с проверкой «вы человек?» помечается
как закрытая и уходит из ролика с честной строкой в отчёте.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from .intake import Item, lookup

# Обычный браузерный заголовок: ролик всё равно снимает настоящий Chrome,
# поэтому проверка смотрит на сайт его глазами. Это не обход защиты.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Признаки страниц-проверок. Регистр не важен. Сильные ловят и при коде 200,
# слабые (капча в форме входа бывает на живом сайте) только при 403, 429 и 503.
CHALLENGE_MARKERS = (
    "just a moment", "cf-chl", "challenge-platform", "checking your browser",
    "ddos-guard", "verify you are human", "are you a robot", "cf-turnstile", "px-captcha",
)
WEAK_MARKERS = ("captcha", "access denied", "attention required")
CHALLENGE_HEADERS = (("cf-mitigated", "challenge"), ("x-vercel-mitigated", "challenge"))

Fetcher = Callable[[str, float], Tuple[int, Dict[str, str], str, str]]


@dataclass
class SiteStatus:
    url: str
    ok: bool
    status: int = 0
    reason: str = ""
    final_url: str = ""
    title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def http_fetch(url: str, timeout: float) -> Tuple[int, Dict[str, str], str, str]:
    """GET без сторонних библиотек. Возвращает код, заголовки, начало тела, итоговый адрес."""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(200_000).decode("utf-8", "replace")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, headers, body, response.geturl()
    except urllib.error.HTTPError as error:
        body = error.read(50_000).decode("utf-8", "replace") if error.fp else ""
        headers = {k.lower(): v for k, v in (error.headers or {}).items()}
        return error.code, headers, body, url


def _title(body: str) -> str:
    low = body.lower()
    start = low.find("<title")
    if start == -1:
        return ""
    start = low.find(">", start) + 1
    end = low.find("</title>", start)
    return " ".join(body[start:end].split())[:120] if end > start else ""


def classify(url: str, status: int, headers: Dict[str, str], body: str, final_url: str) -> SiteStatus:
    low = body.lower()
    title = _title(body)
    for name, value in CHALLENGE_HEADERS:
        if value in headers.get(name, "").lower():
            return SiteStatus(url, False, status, "закрыт защитой от ботов (%s)" % name, final_url, title)
    head = low[:20000]
    hit = next((marker for marker in CHALLENGE_MARKERS if marker in head), None)
    if not hit and status in (403, 429, 503):
        hit = next((marker for marker in WEAK_MARKERS if marker in head), None)
    if hit and (status in (403, 429, 503) or len(body) < 30000):
        return SiteStatus(url, False, status, "закрыт защитой от ботов (%s)" % hit, final_url, title)
    if status >= 500:
        return SiteStatus(url, False, status, "сайт лежит (код %d)" % status, final_url, title)
    if status in (401, 403):
        return SiteStatus(url, False, status, "доступ закрыт (код %d)" % status, final_url, title)
    if status == 404:
        return SiteStatus(url, False, status, "страницы нет (404)", final_url, title)
    if status >= 400:
        return SiteStatus(url, False, status, "ошибка %d" % status, final_url, title)
    if len(body.strip()) < 200:
        return SiteStatus(url, False, status, "пустая страница", final_url, title)
    return SiteStatus(url, True, status, "открывается", final_url, title)


def check_site(url: str, fetch: Optional[Fetcher] = None, timeout: float = 15.0,
               retries: int = 2, pause: float = 1.5) -> SiteStatus:
    """Повторяем только сетевые сбои. Ответ сервера с ошибкой не повторяем."""
    fetch = fetch or http_fetch
    last = ""
    for attempt in range(retries + 1):
        try:
            status, headers, body, final_url = fetch(url, timeout)
            return classify(url, status, headers, body, final_url)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last = str(getattr(error, "reason", error))
            if attempt < retries:
                time.sleep(pause * (attempt + 1))
    return SiteStatus(url, False, 0, "не отвечает: %s" % last[:80])


@dataclass
class Checked:
    item: Item
    status: Optional[SiteStatus]
    verdict: str
    score: float = 0.0


def check_items(items: List[Item], fetch: Optional[Fetcher] = None, offline: bool = False,
                root: Optional[str] = None, retry_blocked: bool = False) -> List[Checked]:
    """Каждый пункт: есть ли ссылка, открывается ли сайт, что знает реестр."""
    out: List[Checked] = []
    for item in items:
        row = lookup(item.name, item.url, root) or {}
        if not item.url:
            out.append(Checked(item, None, "нет ссылки: нужен адрес от автора или ресерч"))
            continue
        if row.get("status") == "blocked" and not retry_blocked:
            # Обычный запрос может пройти, а запись headless-браузером нет: так было в прототипе.
            # Поэтому живой ответ пишем в отчёт, но в ролик сайт не берём без флага --retry-blocked.
            live = "" if offline else " Сейчас по HTTP: %s." % check_site(item.url, fetch).reason
            note = "запись headless закрыта защитой от ботов (замер %s).%s Вернуть: --retry-blocked" % (
                row.get("checked", "-"), live)
            out.append(Checked(item, SiteStatus(item.url, False, 0, note), "пропущен: %s" % note))
            continue
        if offline:
            status = SiteStatus(item.url, True, 0, "сеть выключена, верю реестру" if row else
                                "сеть выключена, не проверял")
        else:
            status = check_site(item.url, fetch)
        verdict = "берём" if status.ok else "пропущен: %s" % status.reason
        out.append(Checked(item, status, verdict))
    return out


def score(checked: Checked, root: Optional[str] = None) -> float:
    """Чем показательнее пункт на экране, тем выше. Механика, вкус остаётся модели."""
    if not checked.status or not checked.status.ok:
        return -1.0
    row = lookup(checked.item.name, checked.item.url, root) or {}
    value = 1.0
    if row.get("recipe"):
        value += 2.0
    if (row.get("demo") or {}).get("query"):
        value += 1.0
    lead = (checked.item.lead or "").lower()
    if any(word in lead for word in ("бесплатн", "free", "без карты", "без регистрации")):
        value += 1.0
    if any(word in lead for word in ("пишем", "описываем", "выбираем", "получаем", "ищет", "type")):
        value += 0.5
    if row.get("found_by_search"):
        value -= 0.5
    return value


def select(checked: List[Checked], per_part: int = 3, root: Optional[str] = None) -> List[List[Checked]]:
    """2-3 лучших пункта на ролик 20-40 секунд, остальное в серию «часть 2».

    Порядок внутри части как в посте: автор уже поставил жирный пункт первым.
    """
    good = [c for c in checked if c.status and c.status.ok]
    for item in good:
        item.score = score(item, root)
    if len(good) <= per_part:
        return [good] if good else []
    ranked = sorted(good, key=lambda c: -c.score)
    parts: List[List[Checked]] = []
    for start in range(0, len(ranked), per_part):
        chunk = ranked[start:start + per_part]
        chunk.sort(key=lambda c: good.index(c))
        parts.append(chunk)
    # Хвост из одного пункта не тянет на ролик: приклеиваем к предыдущей части.
    if len(parts) > 1 and len(parts[-1]) == 1:
        parts[-2].extend(parts.pop())
    return parts


def report_lines(checked: List[Checked]) -> List[str]:
    rows = []
    for c in checked:
        url = c.item.url or "-"
        mark = "+" if c.verdict == "берём" else "x"
        note = ""
        if c.item.url_from == "search":
            note = " (адрес найден поиском, подтверди)"
        rows.append("%s %s: %s, %s%s" % (mark, c.item.name, url, c.verdict, note))
    return rows
