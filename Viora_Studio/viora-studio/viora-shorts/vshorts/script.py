"""Сценарий ролика: каркас из пунктов поста и проверка правил.

Код собирает скелет и ловит нарушения, голос и шутку пишет модель.
Модель может переписать любую реплику в script.json, проверка та же.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .common import emojis, has_dash, is_cyrillic, plural_ru, speech_seconds, words
from .intake import Item, Raw, lookup, norm_name

NUM_WORDS_RU = {1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять", 6: "шесть", 7: "семь"}
NUM_WORDS_RU_F = {1: "одна", 2: "две", 3: "три", 4: "четыре", 5: "пять", 6: "шесть", 7: "семь"}
NUM_WORDS_EN = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}

GREETINGS = ("привет", "здравствуй", "здарова", "всем хай", "хай,", "ребята", "друзья,",
             "доброго времени", "hello", "hi guys", "hey guys", "welcome", "what's up")
FILLERS = ("в этом видео", "в этом ролике", "сегодня я покажу", "сегодня покажу", "смотрите,",
           "давайте посмотрим", "давайте разбер", "in this video", "today i", "let's take a look")
FAREWELLS = ("всем пока", "пока-пока", "до встречи", "увидимся", "до скорого", "bye", "see you",
             "that's all", "на этом всё", "ну всё")
LINK_DESC = ("ссылка в описании", "ссылки в описании", "link in the description",
             "links in the description", "link in description")

# Минимум экранного времени. Сайту нужно успеть открыться и показать результат,
# QR-вспышке в конце нужны 3 секунды (COMMON.md раздел 4).
MIN_SECONDS = {"hook": 2.5, "item": 6.0, "chapter": 4.0, "cta": 3.5, "text": 3.0}
BEAT_PAD = 0.35


@dataclass
class Beat:
    id: str
    kind: str
    say: str
    on_screen: str = ""
    why: str = ""
    item: Optional[Dict[str, Any]] = None
    seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Script:
    lang: str
    beats: List[Beat]
    part: int = 1
    parts: int = 1
    subs: Dict[str, str] = field(default_factory=dict)
    duration_target: List[float] = field(default_factory=lambda: [20.0, 40.0])

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["beats"] = [beat.to_dict() for beat in self.beats]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Script":
        beats = [Beat(**{k: v for k, v in beat.items() if k in Beat.__dataclass_fields__})
                 for beat in data.get("beats", [])]
        return cls(lang=data.get("lang", "ru"), beats=beats, part=int(data.get("part", 1)),
                   parts=int(data.get("parts", 1)), subs=dict(data.get("subs", {})),
                   duration_target=list(data.get("duration_target", [20.0, 40.0])))


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def compress(text: str, limit: int = 16) -> str:
    """Целые предложения, пока влезают в лимит слов. Обрубок фразы хуже короткой фразы."""
    out: List[str] = []
    count = 0
    for sentence in sentences(re.sub(r"\([^)]*\)", "", text or "")):
        size = len(words(sentence))
        if out and count + size > limit:
            break
        if not out and size > limit:
            cut = sentence.split(",")[0].strip()
            out.append(cut.rstrip(".") + ".")
            break
        out.append(sentence)
        count += size
    return " ".join(out).strip()


LIST_SPLIT = re.compile(r"\s*[,:;]\s*|\s+(?:и|или|and|or)\s+")


def list_run(sentence: str) -> int:
    """Самая длинная череда коротких (1-2 слова) элементов через запятую: признак описи."""
    best = run = 0
    for part in LIST_SPLIT.split(sentence.strip().rstrip(".!?")):
        if part and len(words(part)) <= 2:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def shorten_list(sentence: str, keep: int = 3) -> str:
    """Опись из поста в одну живую фразу: первые три вещи и «ещё много всего»."""
    body = sentence.strip().rstrip(".!?")
    if ":" in body:
        body = body.split(":", 1)[1]
    parts = [p.strip() for p in re.split(r"\s*,\s*|\s+и\s+", body) if p.strip()]
    head = parts[:keep]
    if len(parts) <= keep:
        return sentence.strip()
    text = ", ".join(head) + " и ещё много всего."
    return text[:1].upper() + text[1:]


def item_line(item: Item, limit: int = 14) -> str:
    """Одна мысль про пункт: первое предложение, которое не опись и не одно слово."""
    pool = sentences(re.sub(r"\([^)]*\)", "", " ".join([item.lead] + list(item.extra))))
    for sentence in pool:
        if len(words(sentence)) >= 3 and list_run(sentence) < 4 and len(words(sentence)) <= limit + 4:
            # «Дальше», «Также» тянут за собой контекст поста: в ролике его нет.
            sentence = re.sub(r"^(Дальше|Также|Ещё|А ещё|Плюс|Кроме того|Потом|Then|Also)[,:]?\s+", "", sentence)
            return compress(sentence[:1].upper() + sentence[1:], limit)
    lists = [s for s in pool if list_run(s) >= 4]
    if lists:
        return shorten_list(lists[0])
    return compress(" ".join(pool), limit)


def promise(raw: Raw, chosen: List[Item]) -> Optional[str]:
    """Обещание из первой строки поста: «4 находки: шпаргалка по Linux до собеседования и ...»
    даёт «шпаргалка по Linux до собеседования», если это один из показанных пунктов."""
    hook = (raw.hook or "").strip()
    if ":" not in hook:
        return None
    tail = hook.split(":", 1)[1].strip()
    first = re.split(r"\s+и\s+(?=\d)|\s*[,;]\s*|\s+и\s+ещё", tail)[0].strip().rstrip(".!")
    if not 3 <= len(words(first)) <= 11 or re.search(r"\d", first):
        return None
    low = first.lower().replace("ё", "е")
    for item in chosen:
        name = item.name.lower().replace("ё", "е")
        stems = [w[:6] for w in words(name) if len(w) >= 5] + [name]
        if any(stem and stem in low for stem in stems) or any(w[:6] in name for w in words(low) if len(w) >= 6):
            return first
    return None


def estimate(beat: Beat, lang: str, speed: float) -> float:
    talk = speech_seconds(beat.say, lang, speed) + BEAT_PAD
    return round(max(talk, MIN_SECONDS.get(beat.kind, 3.0)), 2)


def _free(raw: Raw, chosen: List[Item]) -> bool:
    blob = " ".join([raw.hook] + [i.lead + " " + " ".join(i.extra) for i in chosen]).lower()
    return "бесплатн" in blob or "free" in blob


def spoken_name(item: Item, lang: str, root: Optional[str] = None) -> str:
    """Как синтезатор читает латинское имя. Кириллические имена читаются как есть."""
    if lang != "ru" or is_cyrillic(item.name):
        return item.name
    row = lookup(item.name, item.url, root) or {}
    table = row.get("say") if isinstance(row.get("say"), dict) else {}
    key = norm_name(item.name)
    for alias, spoken in table.items():
        if norm_name(alias) == key:
            return spoken
    return item.name


def add_subs(subs: Dict[str, str], spoken: str, written: str) -> None:
    """Подмена в субтитрах: первое слово становится именем, остальные пропадают."""
    if spoken == written:
        return
    said = spoken.split()
    subs[said[0]] = written
    for extra in said[1:]:
        subs[extra] = ""


def build(raw: Raw, chosen: List[Item], lang: str = "ru", part: int = 1, parts: int = 1,
          handle: str = "BADVINO", speed: float = 1.05, root: Optional[str] = None,
          noun: str = "сайт") -> Script:
    """Скелет сценария. Для английского нужны английские подводки от модели."""
    if lang != "ru" and any(is_cyrillic(i.lead) for i in chosen):
        raise ValueError("подводки пунктов на русском: для английского ролика модель пишет "
                         "script.json сама (reel.py script --lang en даёт заготовку)")
    chosen = list(chosen)
    lead_promise = promise(raw, chosen) if lang == "ru" else None
    if lead_promise:
        # Пункт из обещания идёт первым: первая секунда показывает именно то, что обещали.
        low = lead_promise.lower().replace("ё", "е")
        hit = next(i for i in chosen if any(w[:6] in low for w in words(i.name.lower().replace("ё", "е")) if len(w) >= 5)
                   or any(w[:6] in i.name.lower().replace("ё", "е") for w in words(low) if len(w) >= 6))
        chosen.remove(hit)
        chosen.insert(0, hit)
    count = len(chosen)
    free = _free(raw, chosen)
    beats: List[Beat] = []
    subs: Dict[str, str] = {}
    names = [spoken_name(i, lang, root) for i in chosen]
    for item, said in zip(chosen, names):
        add_subs(subs, said, item.name)

    if lang == "ru":
        if noun == "находка":
            adj = ("бесплатные" if free else "полезные") if 2 <= count <= 4 else ("бесплатных" if free else "полезных")
            noun_word = plural_ru(count, "находка", "находки", "находок")
            num = NUM_WORDS_RU_F.get(count, str(count)).capitalize()
        else:
            adj = "бесплатных" if free else "полезных"
            noun_word = plural_ru(count, "сайт", "сайта", "сайтов")
            num = NUM_WORDS_RU.get(count, str(count)).capitalize()
        if lead_promise:
            hook_say = lead_promise[:1].upper() + lead_promise[1:]
            if free and "бесплат" not in lead_promise.lower():
                hook_say += ", бесплатно"
            hook_say += "."
            if count > 1:
                rest = count - 1
                if noun == "находка":
                    more = "%s %s" % (NUM_WORDS_RU_F.get(rest, str(rest)), plural_ru(rest, "находка", "находки", "находок"))
                else:
                    more = "%s %s" % (NUM_WORDS_RU.get(rest, str(rest)), plural_ru(rest, "сайт", "сайта", "сайтов"))
                hook_say += " И ещё %s." % more
        else:
            # Без обещания в посте: результат проверки вместо перечня имён.
            hook_say = "%s %s %s, и все работают прямо сейчас." % (num, adj, noun_word) if count > 1 else \
                "%s, и работает прямо сейчас." % ("Бесплатная находка" if free else "Находка")
        hook_screen = "%d %s %s" % (count, adj.upper(), noun_word.upper())
    else:
        adj = "free" if free else "useful"
        noun_word = "site" if count == 1 else "sites"
        hook_say = "%s %s %s that work right now." % (NUM_WORDS_EN.get(count, str(count)).capitalize(), adj, noun_word)
        hook_screen = "%d %s %s" % (count, adj.upper(), noun_word.upper())
    if parts > 1:
        hook_screen += (" | ЧАСТЬ %d" if lang == "ru" else " | PART %d") % part
    beats.append(Beat("hook", "hook", hook_say, hook_screen, "результат и обещание в первую секунду"))

    for index, item in enumerate(chosen, 1):
        name = names[index - 1]
        lead = item_line(item)
        say = "%s. %s" % (name[:1].upper() + name[1:], lead) if lead else "%s." % name
        screen = "%d %s" % (index, item.name.upper())
        beats.append(Beat("item-%d" % index, "item", say.strip(), screen,
                          "польза: показываем сайт в деле", item=item.to_dict()))

    if lang == "ru":
        cta = "Ссылки в закрепе и в канале %s." % handle
        if parts > 1 and part < parts:
            cta = "Продолжение в части %d. %s" % (part + 1, cta)
        screen = "ССЫЛКА В ЗАКРЕПЕ"
    else:
        cta = "Links are in the pinned comment and on the %s channel." % handle
        if parts > 1 and part < parts:
            cta = "Part %d is next. %s" % (part + 1, cta)
        screen = "LINK IN PINNED COMMENT"
    beats.append(Beat("cta", "cta", cta, screen, "один призыв после пользы, петля на первый кадр"))

    script = Script(lang=lang, beats=beats, part=part, parts=parts, subs=subs)
    retime(script, speed)
    return script


def retime(script: Script, speed: float = 1.05) -> None:
    for beat in script.beats:
        beat.seconds = estimate(beat, script.lang, speed)
    fit_low(script)


def fit_low(script: Script, cap: float = 9.0) -> None:
    """Короче цели: показываем сайты дольше (до 9 с), а не дописываем воду в реплики."""
    items = [b for b in script.beats if b.kind in ("item", "chapter")]
    short = script.duration_target[0] - total(script)
    if short <= 0 or not items:
        return
    for beat in items:
        add = min(short / len(items), max(0.0, cap - beat.seconds))
        beat.seconds = round(beat.seconds + add, 2)


def total(script: Script) -> float:
    return round(sum(beat.seconds for beat in script.beats), 2)


def _allowed_numbers(script: Script, raw_text: str) -> set:
    allowed = set(re.findall(r"\d+(?:[.,]\d+)?", raw_text or ""))
    items = sum(1 for b in script.beats if b.kind == "item")
    allowed.update(str(n) for n in range(1, max(items, script.parts) + 2))
    return allowed


def lint(script: Script, raw_text: str = "") -> List[Dict[str, str]]:
    """Правила сценария. ERROR не пускает план к движку, WARN показываем автору."""
    issues: List[Dict[str, str]] = []

    def add(level: str, code: str, msg: str) -> None:
        issues.append({"level": level, "code": code, "message": msg})

    if not script.beats:
        add("ERROR", "E-EMPTY", "в сценарии нет реплик")
        return issues
    allowed = _allowed_numbers(script, raw_text)
    ctas = [i for i, b in enumerate(script.beats) if b.kind == "cta"]
    items = [i for i, b in enumerate(script.beats) if b.kind in ("item", "chapter")]
    first, last = script.beats[0], script.beats[-1]

    for beat in script.beats:
        both = "%s %s" % (beat.say, beat.on_screen)
        low = both.lower()
        if has_dash(both):
            add("ERROR", "E-DASH", "%s: длинное тире, ставим дефис или точку" % beat.id)
        if any(p in low for p in LINK_DESC):
            add("ERROR", "E-LINK-DESC", "%s: в шортсе ссылка не кликабельна, говорим «в закрепе»" % beat.id)
        if any(p in low for p in FILLERS):
            add("ERROR", "E-FILLER", "%s: «в этом видео» и «смотрите» съедают первую секунду" % beat.id)
        if emojis(beat.on_screen):
            add("ERROR", "E-EMOJI-FRAME", "%s: эмодзи как элемент кадра запрещён" % beat.id)
        if len(words(beat.on_screen)) > 6:
            add("WARN", "W-SCREEN-LONG", "%s: текст в кадре длиннее шести слов" % beat.id)
        if beat.kind == "item" and len(words(beat.say)) > 30:
            add("WARN", "W-ITEM-LONG", "%s: реплика длиннее 30 слов, режь до одной мысли" % beat.id)
        if script.lang == "en" and (is_cyrillic(beat.say) or is_cyrillic(beat.on_screen)):
            add("ERROR", "E-LANG", "%s: английский ролик, а в реплике кириллица" % beat.id)
        for number in re.findall(r"\d+(?:[.,]\d+)?", both):
            if number not in allowed:
                add("ERROR", "E-NUMBER", "%s: цифры %s нет в сырье, не выдумываем" % (beat.id, number))

    for beat in script.beats:
        for sentence in sentences(beat.say):
            if list_run(sentence) >= 4:
                add("ERROR", "E-READS-LIST", "%s: опись из поста вслух («%s»): одна мысль, до трёх вещей"
                    % (beat.id, " ".join(sentence.split()[:6])))
    names = []
    for beat in script.beats:
        if beat.item and beat.item.get("name"):
            names.append(beat.item["name"].lower())
    spoken = first.say.lower()
    mentioned = sum(1 for n in names if n in spoken)
    if len(names) >= 2 and mentioned >= min(3, len(names)):
        add("ERROR", "E-HOOK-LIST", "крючок это перечень сайтов, а не результат: скажи, что человек получит")

    low_first = first.say.lower()
    if any(low_first.startswith(g) or (" %s" % g) in low_first[:40] for g in GREETINGS):
        add("ERROR", "E-GREETING", "первая реплика с приветствием: сразу результат или вопрос")
    if len(words(first.say)) > 16:
        add("ERROR", "E-HOOK-LONG", "крючок длиннее 16 слов, первая секунда не вывезет")
    if any(p in last.say.lower() for p in FAREWELLS):
        add("ERROR", "E-FAREWELL", "прощание в конце рвёт петлю")
    if len(ctas) != 1:
        add("ERROR", "E-CTA-COUNT", "призыв должен быть ровно один, сейчас %d" % len(ctas))
    elif items and ctas[0] < items[0]:
        add("ERROR", "E-CTA-EARLY", "призыв стоит до пользы")
    elif ctas and ctas[0] != len(script.beats) - 1:
        add("WARN", "W-CTA-NOT-LAST", "призыв не последний: проверь петлю")
    if not items and len(script.beats) < 3:
        add("WARN", "W-THIN", "в сценарии нет пунктов пользы")

    lo, hi = script.duration_target
    length = total(script)
    if length > hi + 0.01:
        add("ERROR", "E-DURATION-LONG", "оценка %.1f с, верх %.0f с: режь пункт или разбей на серию" % (length, hi))
    elif length < lo - 0.01:
        add("WARN", "W-DURATION-SHORT", "оценка %.1f с, низ %.0f с: добавь деталь или покажи сайт дольше" % (length, lo))
    return issues


def errors(issues: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [i for i in issues if i["level"] == "ERROR"]


def to_markdown(script: Script) -> str:
    rows = ["# Сценарий (%s, часть %d из %d, оценка %.1f с)" % (script.lang, script.part, script.parts, total(script)), ""]
    clock = 0.0
    for beat in script.beats:
        end = clock + beat.seconds
        rows.append("[%s-%s] %s" % (_mmss(clock), _mmss(end), beat.id))
        rows.append("  ГОЛОС: %s" % beat.say)
        if beat.on_screen:
            rows.append("  ЭКРАН: %s" % beat.on_screen)
        rows.append("")
        clock = end
    if script.subs:
        rows.append("Как читать и как писать: " + ", ".join("%s -> %s" % (k, v or "(пусто)") for k, v in script.subs.items()))
    return "\n".join(rows).rstrip() + "\n"


def _mmss(seconds: float) -> str:
    return "%d:%02d" % (int(seconds) // 60, int(seconds) % 60)


def build_html(info: Any, lang: str = "ru", speed_map: Optional[List[Dict[str, float]]] = None,
               handle: str = "BADVINO", voice_speed: float = 1.05,
               duration_target: Optional[List[float]] = None) -> Script:
    """Скелет рассказа про HTML-файл: крючок с лучшим кадром, главы, призыв.

    Реплики глав по умолчанию это их названия. Рассказ голосом Viora пишет модель
    в script.json, код потом проверяет длину, цифры и петлю.
    """
    from .html_adapter import output_length

    speed_map = speed_map or []
    beats: List[Beat] = []
    if lang == "ru":
        hook = "Это один HTML-файл на %d КБ. И вот что он умеет." % info.size_kb
        screen = "ОДИН HTML-ФАЙЛ"
    else:
        hook = "This is a single %d KB HTML file. Watch what it does." % info.size_kb
        screen = "ONE HTML FILE"
    beats.append(Beat("hook", "hook", hook, screen, "самый зрелищный кадр в первую секунду"))
    chapters = info.chapters or []
    for index, chapter in enumerate(chapters, 1):
        title = chapter.title.strip().rstrip(".")
        beat = Beat("chapter-%d" % index, "chapter", title + ".", title.upper()[:40],
                    "глава из таймлайна файла",
                    item={"start": chapter.start, "end": chapter.end, "best": chapter.best})
        beats.append(beat)
    if lang == "ru":
        cta = "Файл и разбор в канале %s, ссылка в закрепе." % handle
        cta_screen = "ССЫЛКА В ЗАКРЕПЕ"
    else:
        cta = "The file and the breakdown are on the %s channel, link in the pinned comment." % handle
        cta_screen = "LINK IN PINNED COMMENT"
    beats.append(Beat("cta", "cta", cta, cta_screen, "один призыв, петля на первый кадр"))
    script = Script(lang=lang, beats=beats, duration_target=duration_target or [25.0, 60.0])
    retime_html(script, speed_map, voice_speed)
    return script


def retime_html(script: Script, speed_map: Optional[List[Dict[str, float]]] = None, voice_speed: float = 1.05) -> None:
    """Глава длится, пока звучит реплика, но не меньше куска таймлайна после ретайма (до 12 с)."""
    from .html_adapter import output_length

    retime(script, voice_speed)
    for beat in script.beats:
        if beat.kind == "chapter" and beat.item:
            shown = output_length(float(beat.item["start"]), float(beat.item["end"]), speed_map or [])
            beat.seconds = round(max(beat.seconds, min(shown, 12.0)), 2)
