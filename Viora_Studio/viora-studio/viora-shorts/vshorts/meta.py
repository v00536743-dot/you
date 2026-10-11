"""Упаковка ролика: 5-7 названий, одно описание, закреп, подпись TikTok и .srt.

Формат из COMMON.md раздел 8 и скрина автора refs/ref-1:
    ТЕКСТ [эмодзи] #shorts #тег #тег
Название честное: обещает только то, что есть в ролике. Цифра в названии
равна числу пунктов, которые реально показаны, а не числу пунктов в посте.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .common import plural_ru, short_link, words

# Тема -> (ярлык в названии по-русски в родительном падеже, по-английски, хэштеги ru, хэштеги en)
TOPICS: Tuple[Tuple[str, str, str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    (r"linux|линукс|bash|ssh", "Linux", "Linux", ("#linux",), ("#linux",)),
    (r"изуч|учёб|учеб|роадмап|гайд|курс|студент|learn|roadmap|guide|course", "учёбы", "learning", ("#учеба",), ("#learning",)),
    (r"\b3d\b|3d-|cad|модел|model", "3D", "3D", ("#3d",), ("#3d",)),
    (r"майнкрафт|minecraft", "Майнкрафта", "Minecraft", ("#minecraft",), ("#minecraft",)),
    (r"нейросет|нейронк|\bии\b|\bai\b|gpt|claude|opus", "нейросетей", "AI", ("#нейросети", "#ии"), ("#ai",)),
    (r"дизайн|интерфейс|ui\b|figma", "дизайна", "design", ("#дизайн",), ("#design",)),
    (r"код|программ|разработ|github|скилл", "кода", "coding", ("#программирование",), ("#coding",)),
    (r"html|three\.?js|canvas|webgl", "веба", "web", ("#html", "#threejs"), ("#html", "#threejs")),
)
BASE_TAGS = {"ru": ("#полезныесайты", "#бесплатно"), "en": ("#usefulsites", "#free")}
SHORTS_TAG = "#shorts"
NUM_RU_CAPS = {2: "ДВА", 3: "ТРИ", 4: "ЧЕТЫРЕ", 5: "ПЯТЬ"}

# Хвост порции субтитров не должен висеть на служебном слове: «шестерёнка с» это брак.
STOP_TAIL = {
    "в", "во", "на", "с", "со", "к", "ко", "у", "о", "об", "от", "до", "из", "за", "по", "для",
    "без", "и", "а", "но", "или", "что", "как", "не", "ни", "же", "при", "про", "под", "над",
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "with", "at", "by", "from", "is",
}


def topics(text: str, lang: str) -> Tuple[List[str], List[str]]:
    low = (text or "").lower()
    labels: List[str] = []
    tags: List[str] = []
    for pattern, ru, en, tags_ru, tags_en in TOPICS:
        if re.search(pattern, low):
            labels.append(ru if lang == "ru" else en)
            for tag in (tags_ru if lang == "ru" else tags_en):
                if tag not in tags:
                    tags.append(tag)
    return labels, tags


def join_list(items: Sequence[str], lang: str) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    glue = " и " if lang == "ru" else " and "
    return ", ".join(items[:-1]) + glue + items[-1]


def _fit(text: str, tags: List[str], limit: int = 100, keep: int = 3) -> str:
    chosen = list(tags)
    line = (text + " " + " ".join(chosen)).strip()
    while len(line) > limit and len(chosen) > keep:
        chosen.pop()
        line = (text + " " + " ".join(chosen)).strip()
    return line


def display_name(item: Dict[str, Any], lang: str) -> str:
    """Имя пункта на языке ролика: name_en от модели, title_en из реестра или как есть."""
    if lang == "en":
        if item.get("name_en"):
            return item["name_en"]
        from .intake import lookup
        row = lookup(item.get("name", ""), item.get("url")) or {}
        if row.get("title_en"):
            return row["title_en"]
    return item["name"]


def facts_from(items: List[Dict[str, Any]], lang: str, free: bool, part: int = 1, parts: int = 1,
               noun: str = "сайт") -> Dict[str, Any]:
    names = [display_name(i, lang) for i in items]
    blob = " ".join(i["name"] + " " + i.get("lead", "") for i in items)
    labels, tags = topics(blob, lang)
    return {"lang": lang, "count": len(items), "names": names, "free": free, "labels": labels[:3],
            "topic_tags": tags, "part": part, "parts": parts, "noun": noun,
            "leads": [i.get("lead", "") for i in items],
            "urls": [i.get("url") for i in items if i.get("url")]}


def hashtag_sets(facts: Dict[str, Any]) -> Dict[str, List[str]]:
    lang = facts["lang"]
    base = list(BASE_TAGS[lang]) if facts.get("free") else [BASE_TAGS[lang][0]]
    topic = list(facts["topic_tags"])
    title = [SHORTS_TAG] + topic[:3] + base[:2]
    top = (topic + base)[:3]
    bottom = [SHORTS_TAG] + [t for t in (base + topic) if t not in top][:4]
    if len(bottom) < 3:
        bottom += [t for t in (["#shortsvideo"] if lang == "en" else ["#находки"]) if t not in bottom]
    return {"title": title[:6], "top": top, "bottom": bottom[:6]}


def _noun_ru(count: int, noun: str) -> Tuple[str, str]:
    if noun == "находка":
        return plural_ru(count, "БЕСПЛАТНАЯ НАХОДКА", "БЕСПЛАТНЫЕ НАХОДКИ", "БЕСПЛАТНЫХ НАХОДОК"), \
            plural_ru(count, "бесплатная находка", "бесплатные находки", "бесплатных находок")
    return plural_ru(count, "БЕСПЛАТНЫЙ САЙТ", "БЕСПЛАТНЫХ САЙТА", "БЕСПЛАТНЫХ САЙТОВ"), \
        plural_ru(count, "бесплатный сайт", "бесплатных сайта", "бесплатных сайтов")


def titles(facts: Dict[str, Any], history: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
    """Шесть вариантов от громкого (1) к консервативному (5). Цифры только из фактов."""
    lang, n, names = facts["lang"], facts["count"], facts["names"]
    tags = hashtag_sets(facts)["title"]
    topic = join_list(facts["labels"], lang)
    part = " | часть %d" % facts["part"] if facts.get("parts", 1) > 1 else ""
    if lang == "en":
        part = " | part %d" % facts["part"] if facts.get("parts", 1) > 1 else ""
        free = "FREE" if facts["free"] else "USEFUL"
        rows = [
            (1, "интрига", "%d %s SITES FOR %s 😱%s" % (n, free, (topic or "WORK").upper(), part)),
            (2, "интрига", "%s AND %d MORE, ALL %s 🔥%s" % (names[0].upper(), n - 1, free, part) if n > 1
             else "%s IS %s 🔥%s" % (names[0].upper(), free, part)),
            (3, "интрига", "Save this: %d %s sites for %s%s" % (n, free.lower(), topic or "work", part)),
            (3, "поиск", "%d %s sites for %s you will actually use%s" % (n, free.lower(), topic or "work", part)),
            (4, "поиск", "%s: what they do for free%s" % (join_list(names, lang), part)),
            (5, "поиск", "%s sites for %s: %s%s" % (free.capitalize(), topic or "work", ", ".join(names), part)),
        ]
    else:
        caps, plain = _noun_ru(n, facts.get("noun", "сайт"))
        num = NUM_RU_CAPS.get(n, str(n))
        target = (" ДЛЯ " + topic.upper()) if topic else ""
        target_low = (" для " + topic) if topic else ""
        rows = [
            (1, "интрига", "%d %s%s 😱%s" % (n, caps, target, part)),
            (2, "интрига", "%s И ЕЩЁ %d: ВСЁ БЕСПЛАТНО 🔥%s" % (names[0].upper(), n - 1, part) if n > 1
             else "%s БЕСПЛАТНО 🔥%s" % (names[0].upper(), part)),
            (3, "интрига", "Сохрани: %s %s%s%s" % (num.lower(), plain, target_low, part)),
            (3, "поиск", "%d %s%s, которые реально пригодятся%s" % (n, plain, target_low, part)),
            (4, "поиск", "%s: что умеют бесплатно%s" % (join_list(names, lang), part)),
            (5, "поиск", "Бесплатные сайты%s: %s%s" % (target_low, ", ".join(names), part)),
        ]
    out = []
    for loudness, kind, text in rows:
        line = _fit(text, tags)
        for cut in range(len(names) - 1, 0, -1):
            if len(line) <= 100:
                break
            short = ", ".join(names[:cut])
            line = _fit(text.replace(", ".join(names), short).replace(join_list(names, lang), join_list(names[:cut], lang)), tags)
        out.append({"text": line, "loudness": loudness, "for": kind,
                    "why": WHY[(loudness, kind)], "recommended": False})
    pick = _recommend(out, history)
    out[pick]["recommended"] = True
    return out


WHY = {
    (1, "интрига"): "капс, цифра и эмодзи: шаблон автора, лучше всего держит ленту Shorts",
    (2, "интрига"): "имя самого сильного сайта первым, остальное интригой",
    (3, "интрига"): "мягкий призыв сохранить: работает на повторный просмотр",
    (3, "поиск"): "цифра и польза без капса: баланс ленты и поиска",
    (4, "поиск"): "имена сервисов в начале: их будут искать по названию",
    (5, "поиск"): "поисковая фраза без капса и эмодзи: для поиска и канала",
}


def _recommend(rows: List[Dict[str, Any]], history: Optional[Dict[str, List[str]]]) -> int:
    """По умолчанию громкий шаблон автора. Если автор раньше выбирал тише, идём за ним."""
    chosen = (history or {}).get("chosen") or []
    if not chosen:
        return 0
    def loud(text: str) -> float:
        letters = [c for c in text.split("#")[0] if c.isalpha()]
        return sum(1 for c in letters if c.isupper()) / max(1, len(letters))
    mean = sum(loud(t) for t in chosen[-5:]) / len(chosen[-5:])
    target = 1 if mean > 0.6 else (3 if mean > 0.2 else 5)
    return min(range(len(rows)), key=lambda i: abs(rows[i]["loudness"] - target))


def description(facts: Dict[str, Any], links: Dict[str, str]) -> str:
    """Одно описание: три тега сверху, суть, один призыв, ссылки автора, теги снизу."""
    lang = facts["lang"]
    tags = hashtag_sets(facts)
    names = join_list(facts["names"], lang)
    topic = join_list(facts["labels"], lang)
    first_lead = ""
    for lead in facts.get("leads", []):
        sentence = re.split(r"(?<=[.!?])\s+", lead.strip())[0] if lead else ""
        if sentence:
            first_lead = sentence.rstrip(".") + "."
            break
    if lang == "ru":
        _, plain = _noun_ru(facts["count"], facts.get("noun", "сайт"))
        summary = "%s: %d %s%s." % (names, facts["count"], plain, (" для " + topic) if topic else "")
        cta = "Ещё находки и все ссылки в Телеграм-канале."
        rows = [" ".join(tags["top"]), summary + (" " + first_lead if first_lead else ""), "", cta]
        if links.get("telegram"):
            rows.append("Telegram: %s" % links["telegram"])
        if links.get("youtube"):
            rows.append("YouTube: %s" % links["youtube"])
    else:
        free = "free" if facts["free"] else "useful"
        summary = "%s: %d %s sites%s." % (names, facts["count"], free, (" for " + topic) if topic else "")
        cta = "More finds and all links on the Telegram channel."
        rows = [" ".join(tags["top"]), summary, "", cta]
        if links.get("telegram"):
            rows.append("Telegram: %s" % links["telegram"])
        if links.get("youtube"):
            rows.append("YouTube: %s" % links["youtube"])
    rows += ["", " ".join(tags["bottom"])]
    return "\n".join(rows).strip() + "\n"


def pinned(facts: Dict[str, Any], links: Dict[str, str], post_url: Optional[str] = None) -> str:
    """Закреп на три строки: в шортсе ссылки кликабельны только здесь."""
    lang = facts["lang"]
    urls = " | ".join(short_link(u) for u in facts.get("urls", []))
    rows = []
    if lang == "ru":
        if urls:
            rows.append("Сайты из ролика: %s" % urls)
        if post_url:
            rows.append("Пост с разбором: %s" % post_url)
        if links.get("telegram"):
            rows.append("Ещё находки каждый день: %s" % links["telegram"])
    else:
        if urls:
            rows.append("Sites from the video: %s" % urls)
        if post_url:
            rows.append("Full breakdown: %s" % post_url)
        if links.get("telegram"):
            rows.append("More finds every day: %s" % links["telegram"])
    return "\n".join(rows[:3]) + "\n"


def tiktok(facts: Dict[str, Any]) -> str:
    tags = hashtag_sets(facts)
    pool = [t for t in tags["top"] + tags["bottom"] if t != SHORTS_TAG]
    unique = list(dict.fromkeys(pool))[:5]
    if facts["lang"] == "ru":
        text = "%s. Ссылки в профиле." % join_list(facts["names"], "ru")
    else:
        text = "%s. Links in bio." % join_list(facts["names"], "en")
    return (text + " " + " ".join(unique)).strip() + "\n"


def apply_subs(text: str, subs: Dict[str, str]) -> str:
    """Как читали -> как пишем. Пустая подмена убирает слово (хвост длинного имени)."""
    out = []
    for token in text.split():
        core = token.strip(".,!?:;")
        tail = token[len(core):] if token.startswith(core) else ""
        if core in subs:
            if subs[core]:
                out.append(subs[core] + tail)
            elif tail and out:
                out[-1] += tail
        else:
            out.append(token)
    return " ".join(out)


def chunk_words(text: str, max_words: int = 3) -> List[str]:
    """Порции по 2-3 слова: режем по знакам препинания, не оставляем предлог в хвосте."""
    tokens = text.split()
    chunks: List[List[str]] = []
    current: List[str] = []
    for index, token in enumerate(tokens):
        current.append(token)
        # Конец фразы режет всегда, запятая только если в порции уже два слова:
        # иначе перечисление мигает по одному слову.
        ends_phrase = token[-1:] in ".!?:;" or (token[-1:] == "," and len(current) >= 2)
        last_word = token.strip(".,!?:;").lower()
        full = len(current) >= max_words
        if ends_phrase or full:
            if not ends_phrase and last_word in STOP_TAIL and index + 1 < len(tokens):
                if len(current) > 1:
                    carry = current.pop()
                    chunks.append(current)
                    current = [carry]
                continue
            chunks.append(current)
            current = []
    if current:
        if chunks and len(current) == 1 and len(chunks[-1]) < max_words and chunks[-1][-1][-1:] not in ".!?":
            chunks[-1].extend(current)
        else:
            chunks.append(current)
    return [" ".join(c) for c in chunks]


def srt_from_script(beats: List[Dict[str, Any]], subs: Dict[str, str], max_words: int = 3) -> str:
    """Оценочный .srt по длинам реплик. Точный даёт движок по границам слов TTS."""
    rows: List[str] = []
    clock = 0.0
    index = 1
    for beat in beats:
        shown = apply_subs(beat["say"], subs)
        parts = chunk_words(shown, max_words)
        if not parts:
            clock += beat["seconds"]
            continue
        weights = [max(1, len(words(p))) for p in parts]
        unit = beat["seconds"] / sum(weights)
        for part, weight in zip(parts, weights):
            start, end = clock, clock + unit * weight
            rows.append("%d\n%s --> %s\n%s\n" % (index, _ts(start), _ts(end), part))
            index += 1
            clock = end
    return "\n".join(rows)


def srt_from_words(words_timed: List[Dict[str, Any]], subs: Dict[str, str], max_words: int = 3) -> str:
    """Точный .srt по таймингам слов от движка: [{"word":..,"start":..,"end":..}]."""
    text = " ".join(w["word"] for w in words_timed)
    parts = chunk_words(text, max_words)
    rows = []
    cursor = 0
    for index, part in enumerate(parts, 1):
        size = len(part.split())
        span = words_timed[cursor:cursor + size]
        cursor += size
        if not span:
            break
        rows.append("%d\n%s --> %s\n%s\n" % (index, _ts(span[0]["start"]), _ts(span[-1]["end"]),
                                             apply_subs(part, subs)))
    return "\n".join(rows)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def package(facts: Dict[str, Any], links: Dict[str, str], history: Optional[Dict[str, List[str]]] = None,
            post_url: Optional[str] = None) -> Dict[str, Any]:
    allowed = [u for u in (links.get("telegram"), links.get("youtube"), links.get("chat")) if u]
    return {
        "lang": facts["lang"],
        "titles": titles(facts, history),
        "description": description(facts, links),
        "pinned": pinned(facts, links, post_url),
        "tiktok": tiktok(facts),
        "hashtags": hashtag_sets(facts),
        "links_allowed": allowed + list(facts.get("urls", [])) + ([post_url] if post_url else []),
    }


def titles_markdown(meta: Dict[str, Any]) -> str:
    rows = ["# Названия (1 громкое, 5 консервативное)", ""]
    for row in meta["titles"]:
        mark = "  <- беру это" if row["recommended"] else ""
        rows.append("%d. [%d, %s] %s%s" % (meta["titles"].index(row) + 1, row["loudness"], row["for"], row["text"], mark))
        rows.append("   почему: %s" % row["why"])
    return "\n".join(rows) + "\n"
