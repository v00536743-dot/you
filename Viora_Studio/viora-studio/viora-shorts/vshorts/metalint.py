"""Правила названий, описаний, закрепа и подписи TikTok. Используют lint_video_meta.py и farm.

Коды как у линтера постов: E- ломает выдачу, W- показываем автору.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .common import DASHES, URL_RE, emojis, has_dash, hashtags, is_cyrillic

TITLE_MAX = 100
TITLES_MIN, TITLES_MAX = 5, 7
TITLE_TAGS = (3, 6)
TOP_TAGS_MAX = 3
TIKTOK_TAGS_MAX = 5
UNIQUE_TAGS_MAX = 15
YOUTUBE_TAGS_HARD = 60
PINNED_LINES = 3

# Обещания, которые ролик почти никогда не выполняет. Название обязано быть честным.
CLICKBAIT = ("вы не поверите", "это изменит", "шок", "никто не знает", "о которых молчат",
             "100%", "гарантированно", "you won't believe", "nobody knows", "will change your life")
LINK_DESC = ("ссылка в описании", "ссылки в описании", "link in the description", "link in description")


def _caps_ratio(text: str) -> float:
    head = text.split("#")[0]
    letters = [c for c in head if c.isalpha()]
    return sum(1 for c in letters if c.isupper()) / max(1, len(letters))


def lint(meta: Dict[str, Any]) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []

    def add(level: str, code: str, msg: str) -> None:
        issues.append({"level": level, "code": code, "message": msg})

    lang = meta.get("lang", "ru")
    rows = meta.get("titles") or []
    if not TITLES_MIN <= len(rows) <= TITLES_MAX:
        add("ERROR", "E-TITLE-COUNT", "вариантов названия %d, нужно 5-7" % len(rows))
    seen = set()
    last_loud = 0
    rec = 0
    for index, row in enumerate(rows, 1):
        text = row.get("text", "") if isinstance(row, dict) else str(row)
        loud = int(row.get("loudness", 0)) if isinstance(row, dict) else 0
        rec += 1 if isinstance(row, dict) and row.get("recommended") else 0
        where = "название %d" % index
        if not text.strip():
            add("ERROR", "E-TITLE-EMPTY", "%s пустое" % where)
            continue
        if len(text) > TITLE_MAX:
            add("ERROR", "E-TITLE-LONG", "%s: %d знаков, максимум %d" % (where, len(text), TITLE_MAX))
        if len(emojis(text)) > 1:
            add("ERROR", "E-TITLE-EMOJI", "%s: эмодзи больше одного" % where)
        tags = hashtags(text)
        if not TITLE_TAGS[0] <= len(tags) <= TITLE_TAGS[1]:
            add("ERROR", "E-TITLE-TAGS", "%s: хэштегов %d, по шаблону автора 3-6" % (where, len(tags)))
        if text.lstrip().startswith("#"):
            add("ERROR", "E-TITLE-TAG-FIRST", "%s: начинается с хэштега, ключевое слово должно быть первым" % where)
        if loud and not 1 <= loud <= 5:
            add("ERROR", "E-TITLE-LOUD", "%s: громкость %d вне шкалы 1-5" % (where, loud))
        if loud and loud < last_loud:
            add("ERROR", "E-TITLE-ORDER", "%s: порядок от громкого к консервативному нарушен" % where)
        last_loud = max(last_loud, loud)
        if loud >= 3 and _caps_ratio(text) > 0.5:
            add("ERROR", "E-TITLE-CAPS", "%s: капс разрешён только в громких вариантах 1-2" % where)
        if loud == 5 and emojis(text):
            add("ERROR", "E-TITLE-QUIET-EMOJI", "%s: консервативный вариант без эмодзи" % where)
        low = text.lower()
        bait = next((b for b in CLICKBAIT if b in low), None)
        if bait:
            add("ERROR", "E-TITLE-BAIT", "%s: «%s» это кликбейт, YouTube режет за обман" % (where, bait))
        if lang == "en" and is_cyrillic(text):
            add("ERROR", "E-LANG", "%s: английский режим, а в названии кириллица" % where)
        key = re.sub(r"\W+", "", text.split("#")[0].lower())
        if key in seen:
            add("ERROR", "E-TITLE-DUP", "%s повторяет другой вариант" % where)
        seen.add(key)
        if isinstance(row, dict) and not row.get("why"):
            add("WARN", "W-TITLE-WHY", "%s без пометки «почему»" % where)
    if rows and rec != 1:
        add("ERROR", "E-TITLE-RECOMMEND", "рекомендованный вариант должен быть ровно один, сейчас %d" % rec)

    desc = meta.get("description")
    if isinstance(desc, list):
        add("ERROR", "E-DESC-COUNT", "описаний %d, нужно ОДНО" % len(desc))
        desc = desc[0] if desc else ""
    desc = desc or ""
    if not desc.strip():
        add("ERROR", "E-DESC-EMPTY", "описания нет")
    else:
        lines = desc.strip().splitlines()
        top = hashtags(lines[0])
        if not lines[0].strip().startswith("#") or not 1 <= len(top) <= TOP_TAGS_MAX:
            add("ERROR", "E-DESC-TOP", "первая строка описания: 1-3 хэштега, они встанут над названием")
        body = "\n".join(lines[1:])
        if not hashtags(lines[-1]) or lines[-1] == lines[0]:
            add("WARN", "W-DESC-BOTTOM", "нет нижнего блока хэштегов")
        allowed = set(meta.get("links_allowed") or [])
        urls = URL_RE.findall(body)
        if allowed and not any(u in allowed for u in urls):
            add("ERROR", "E-DESC-NO-LINK", "в описании нет ссылки автора")
        for url in urls:
            if allowed and url.rstrip(".,") not in allowed:
                add("ERROR", "E-DESC-STRANGE-LINK", "ссылка %s не из настроек и не из ролика: не выдумываем" % url)
        if lang == "en" and is_cyrillic(body):
            add("ERROR", "E-LANG", "английский режим, а в описании кириллица")
    every = " ".join([r.get("text", "") if isinstance(r, dict) else str(r) for r in rows] + [desc])
    unique = {t.lower() for t in hashtags(every)}
    if len(unique) > YOUTUBE_TAGS_HARD:
        add("ERROR", "E-TAGS-60", "хэштегов больше 60: YouTube проигнорирует все")
    elif len(unique) > UNIQUE_TAGS_MAX:
        add("WARN", "W-TAGS-MANY", "уникальных хэштегов %d, держим до 15" % len(unique))
    desc_tags = [t.lower() for t in hashtags(desc)]
    if len(desc_tags) != len(set(desc_tags)):
        add("WARN", "W-TAG-REPEAT", "в описании один хэштег дважды")

    pinned = meta.get("pinned") or ""
    if pinned and len([l for l in pinned.splitlines() if l.strip()]) > PINNED_LINES:
        add("ERROR", "E-PINNED-LONG", "закреп длиннее трёх строк")
    if not pinned.strip():
        add("ERROR", "E-PINNED-EMPTY", "нет закрепа: в шортсе это единственная живая ссылка")
    tik = meta.get("tiktok") or ""
    if len(hashtags(tik)) > TIKTOK_TAGS_MAX:
        add("ERROR", "E-TIKTOK-TAGS", "в подписи TikTok больше пяти хэштегов")

    blob = every + "\n" + pinned + "\n" + tik
    if has_dash(blob):
        add("ERROR", "E-DASH", "длинное тире: только дефис (правило ноль)")
    low = blob.lower()
    if any(p in low for p in LINK_DESC):
        add("ERROR", "E-LINK-DESC", "«ссылка в описании» не работает в шортсах, пишем «в закрепе»")
    return issues


def errors(issues: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [i for i in issues if i["level"] == "ERROR"]


def good_sample() -> Dict[str, Any]:
    tg = "https://t.me/VioraStudio"
    return {
        "lang": "ru",
        "titles": [
            {"text": "3 БЕСПЛАТНЫХ САЙТА ДЛЯ LINUX, УЧЁБЫ И 3D 😱 #shorts #linux #учеба #3d", "loudness": 1, "for": "интрига", "why": "шаблон автора", "recommended": True},
            {"text": "LEARN-ANYTHING И ЕЩЁ 2: ВСЁ БЕСПЛАТНО 🔥 #shorts #linux #учеба", "loudness": 2, "for": "интрига", "why": "имя первым"},
            {"text": "Сохрани: три бесплатных сайта для учёбы #shorts #учеба #3d", "loudness": 3, "for": "интрига", "why": "сохранение"},
            {"text": "3 бесплатных сайта, которые реально пригодятся #shorts #учеба #бесплатно", "loudness": 3, "for": "поиск", "why": "баланс"},
            {"text": "learn-anything и cad-search: что умеют бесплатно #shorts #учеба #3d", "loudness": 4, "for": "поиск", "why": "имена"},
            {"text": "Бесплатные сайты для учёбы: learn-anything, cad-search #shorts #учеба #3d", "loudness": 5, "for": "поиск", "why": "поиск"},
        ],
        "description": "#linux #учеба #3d\nТри бесплатных сайта для учёбы и 3D.\n\nЕщё находки в Телеграм-канале.\nTelegram: %s\n\n#shorts #полезныесайты #бесплатно\n" % tg,
        "pinned": "Сайты из ролика: learn-anything.xyz | cadlookup.com\nЕщё находки: %s\n" % tg,
        "tiktok": "learn-anything и cad-search. Ссылки в профиле. #linux #учеба #3d\n",
        "links_allowed": [tg],
    }


def selftest_cases() -> List[Any]:
    """(имя, мета, ожидаемый код или None для чистого)."""
    import copy

    cases: List[Any] = [("чистый пакет", good_sample(), None)]

    def bad(name: str, code: str, mutate: Any) -> None:
        data = copy.deepcopy(good_sample())
        mutate(data)
        cases.append((name, data, code))

    bad("четыре названия", "E-TITLE-COUNT", lambda d: d["titles"].__delitem__(slice(1, 3)))
    bad("название длиннее 100", "E-TITLE-LONG", lambda d: d["titles"][0].update(text="А" * 95 + " 😱 #shorts #a #b"))
    bad("два эмодзи", "E-TITLE-EMOJI", lambda d: d["titles"][0].update(text="ТРИ САЙТА 😱🔥 #shorts #a #b"))
    bad("один хэштег", "E-TITLE-TAGS", lambda d: d["titles"][0].update(text="ТРИ САЙТА 😱 #shorts"))
    bad("порядок громкости", "E-TITLE-ORDER", lambda d: d["titles"][2].update(loudness=1))
    bad("капс в тихом", "E-TITLE-CAPS", lambda d: d["titles"][3].update(text="ТРИ БЕСПЛАТНЫХ САЙТА ДЛЯ ВСЕХ #shorts #a #b"))
    bad("кликбейт", "E-TITLE-BAIT", lambda d: d["titles"][0].update(text="САЙТЫ, О КОТОРЫХ МОЛЧАТ 😱 #shorts #a #b"))
    bad("два рекомендованных", "E-TITLE-RECOMMEND", lambda d: d["titles"][1].update(recommended=True))
    bad("длинное тире", "E-DASH", lambda d: d.update(description=d["description"].replace("Три", "Три \u2014 [dash-demo]")))
    bad("два описания", "E-DESC-COUNT", lambda d: d.update(description=[d["description"], d["description"]]))
    bad("нет тегов сверху", "E-DESC-TOP", lambda d: d.update(description=d["description"].split("\n", 1)[1]))
    bad("выдуманная ссылка", "E-DESC-STRANGE-LINK", lambda d: d.update(description=d["description"].replace("Telegram:", "Сайт: https://example.com\nTelegram:")))
    bad("ссылка в описании", "E-LINK-DESC", lambda d: d.update(pinned="Ссылка в описании\n"))
    bad("закреп на 4 строки", "E-PINNED-LONG", lambda d: d.update(pinned="1\n2\n3\n4\n"))
    bad("шесть тегов TikTok", "E-TIKTOK-TAGS", lambda d: d.update(tiktok="x #a #b #c #d #e #f\n"))
    bad("английский с кириллицей", "E-LANG", lambda d: d.update(lang="en"))
    bad("хэштег первым", "E-TITLE-TAG-FIRST", lambda d: d["titles"][5].update(text="#shorts сайты для учёбы #a #b"))
    bad("эмодзи в консервативном", "E-TITLE-QUIET-EMOJI", lambda d: d["titles"][5].update(text="Бесплатные сайты для учёбы 🔥 #shorts #a #b"))
    return cases
