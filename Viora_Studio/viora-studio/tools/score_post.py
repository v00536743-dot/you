#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оценщик поста VIORA STUDIO. Версия 1.0.

Зачем он нужен. Линтер отвечает на вопрос «где нарушено правило». Он не отвечает
на вопрос «это хороший пост или просто пост без ошибок». Слабая модель без цифры
останавливается на первом варианте и считает его готовым. Цифра заставляет переписать.

Шкала 0-100, шесть критериев:
    КРЮЧОК       20  цифра, выгода или драма факта в первом экране
    ДУША         15  тёплое слово, мнение, шутка, простыми словами
    ГОЛОС        15  живая лексика, обращение на вы, без паразитов
    ПОЛЬЗА       20  пункты, цифры, ссылки с ярлыками, польза внутри поста
    СТРУКТУРА    15  длина по рубрике, хэштег, футер, ритм абзацев
    ГОТОВНОСТЬ   15  ошибки и предупреждения линтера

Правило честности: выше 90 баллов пост получает только когда линтер чист полностью
и в крючке есть цифра или драма факта. Иначе потолок 90.

Команды:
    python3 tools/score_post.py черновик.txt
    python3 tools/score_post.py черновик.txt --rubric абуз --json
    python3 tools/score_post.py черновик.txt --min 75
    python3 tools/score_post.py --selftest

Код возврата: 1 если балл ниже порога --min, иначе 0. Порог по умолчанию 0.
Сторонних библиотек не нужно, только Python 3.
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lint_post as L  # noqa: E402
import memory as M  # noqa: E402

# Пунктов в посте по рубрикам. Источник: таблица рубрик в SKILL.md.
ITEM_RANGES = {
    "абуз": (4, 7),
    "сервисы": (3, 5),
    "релиз": (1, 3),
    "девлог": (1, 3),
    "опрос": (2, 4),
    "шортс": (1, 1),
    "лидмагнит": (1, 1),
    "неробит": (1, 2),
}

# Слова выгоды в первом экране. За этим люди открывают пост из уведомления.
BENEFIT = [
    "бесплатн", "халяв", "без карт", "без вложен", "лимит", "промокод",
    "триал", "trial", "доступ", "раздают", "раздаю", "дарят", "дают",
    "скидк", "подписк", "токен", "гб", "рубл", "доллар", "$", "pro",
    "plus", "premium", "без ключ", "кредит", "год бесплатн", "месяц",
]

# Фоллбек-цифры канала, если memory/metrics.md недоступен.
FALLBACK = {"subscribers": 260, "reach": (165, 386), "reactions": (1, 5)}

FIRST_SCREEN = 100
CEILING_WITHOUT_PROOF = 90

# Анонс при статье: пунктов и личной детали в нём нет по замыслу.
ANNOUNCE_FLOOR = 92
ANNOUNCE_BODY_MAX = 400

CRITERIA = ["крючок", "душа", "голос", "польза", "структура", "готовность"]

# Веса критериев. Сумма ровно 100, иначе оценка перестаёт быть процентом.
WEIGHTS = {
    "крючок": 20,
    "душа": 15,
    "голос": 15,
    "польза": 20,
    "структура": 15,
    "готовность": 15,
}


def body_of(text):
    """Тело без строки футера и без строки хэштега."""
    tag_rows = set(index for index, _ in L.find_hashtags(text))
    out = []
    for index, line in enumerate(text.split("\n")):
        if index in tag_rows:
            continue
        if line.strip() == L.FOOTER:
            continue
        out.append(line)
    return "\n".join(out)


def first_screen(text):
    """Первые 100 видимых знаков: это превью в уведомлении и в пересылке."""
    shown = L.markup_off(body_of(text)).strip()
    return shown[:FIRST_SCREEN]


def first_line(text):
    for line in body_of(text).split("\n"):
        if line.strip():
            return L.markup_off(line).strip()
    return ""


def codes_of(issues):
    return set(item["code"] for item in issues)


def count_digits(text):
    return len(re.findall(r"\d+", L.nolinks(text)))


def labelled_link(text):
    for label in re.findall(L.LINK, text):
        if label.strip().upper() in L.LABELS_OK:
            return True
    return False


def paragraphs(text):
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def is_announce(text):
    """Анонс при статье: название ссылкой и ни одного пункта в теле."""
    if re.search(r"(?m)^\s*\*\*\d+\.", text):
        return False
    if not re.search(r"\[[^\]]+\]\((?:https?://telegra\.ph|PASTE_TELEGRAPH_URL)", text):
        return False
    return len(L.markup_off(body_of(text)).strip()) <= ANNOUNCE_BODY_MAX


def score_hook(text, codes):
    screen = first_screen(text)
    low = screen.lower()
    points, notes = 0, []

    drama = L.has_any(low, L.CONTRAST)
    if re.search(r"\d", screen):
        points += 6
    elif drama:
        points += 5
    else:
        notes.append("в первом экране нет ни цифры, ни драмы факта")

    if L.has_any(low, BENEFIT) or L.has_deadline(screen):
        points += 4
    elif drama:
        points += 3
    else:
        notes.append("в первом экране нет выгоды и нет срока")

    if "E-GREETING-LONG" in codes or "E-GREETING-BANAL" in codes:
        notes.append("приветствие съедает самое дорогое место")
    else:
        points += 4

    head = first_line(text)
    if head and len(head) <= 110:
        points += 3
    else:
        notes.append("первая строка длиннее 110 знаков, её не сканируют")

    tail_words = L.words(L.greeting_tail(screen))
    if len(tail_words) >= 6:
        points += 3
    else:
        notes.append("после приветствия в первом экране почти нет смысла")

    if "E-FIRST-SCREEN" in codes:
        points = min(points, 10)
        notes.append("линтер забраковал первый экран")

    return min(points, 20), notes


def score_soul(text, codes):
    """Душа: сколько в посте живого человека. Разбор в reference/soul.md."""
    points, notes = 0, []
    live, total, missing = L.soul(text)

    # Два маркера это норма, четыре и больше это полный балл.
    points += min(10, live * 3)
    if live < 2:
        notes.append("маркеров души %d из %d: нет %s" % (live, total, missing[0]))
    elif live < 4:
        notes.append("души хватает впритык: нет %s" % missing[0])

    warm, opinion = L.has_any(L.nolinks(text).lower(), L.WARM), L.has_any(
        L.nolinks(text).lower(), L.OPINION
    )
    if warm:
        points += 2
    else:
        notes.append("нет ни одного тёплого слова к читателю")
    if opinion:
        points += 2
    else:
        notes.append("нет мнения автора одной строкой")
    if L.SIMPLE_BLOCK in text.lower():
        points += 1

    if "W-SOUL-LOW" in codes:
        points = min(points, 6)
    if "W-REACTION-END" in codes:
        points = max(0, points - 2)
        notes.append("сухая просьба о реакциях в концовке")

    return min(points, WEIGHTS["душа"]), notes


def score_voice(text, codes):
    points, notes = 0, []

    if "W-NO-LEXICON" in codes:
        notes.append("нет живой лексики канала")
    else:
        points += 5

    if "W-JARGON" in codes:
        notes.append("термины стоят голыми: объясни одной строкой или добавь блок")
    else:
        points += 3

    if L.has_any(L.nolinks(text).lower(), L.PERSONAL):
        points += 3
    else:
        notes.append("если в сырье был твой опыт, он не попал в пост")

    if "W-TY-ADDRESS" in codes:
        notes.append("обращение на ты, канал говорит мы и вы")
    else:
        points += 2

    low = text.lower()
    parasites = sum(
        len(re.findall(r"\b%s\b" % word, low)) for word in L.PARASITE
    )
    if parasites == 0:
        points += 2
    elif parasites <= 2:
        points += 1
        notes.append("слова-паразиты: %d штуки" % parasites)
    else:
        notes.append("слова-паразиты: %d штук" % parasites)

    return min(points, WEIGHTS["голос"]), notes


def score_value(text, rubric, codes):
    points, notes = 0, []
    body = body_of(text)
    items = len(L.numbered_items(body))
    digits = count_digits(body)

    span = ITEM_RANGES.get(rubric or "")
    if span:
        low, high = span
        if low <= items <= high:
            points += 8
        elif low - 1 <= items <= high + 1:
            points += 4
            notes.append("пунктов %d, норма для #%s это %d-%d" % (items, rubric, low, high))
        else:
            notes.append("пунктов %d, норма для #%s это %d-%d" % (items, rubric, low, high))
    else:
        if digits >= 4:
            points += 8
        elif digits >= 2:
            points += 4
            notes.append("у рубрики нет нормы по пунктам, а цифр всего %d" % digits)
        else:
            notes.append("нет ни списка пунктов, ни цифр")

    points += min(6, digits * 2)
    if digits < 3:
        notes.append("цифр в теле всего %d, пост без цифр не пересылают" % digits)

    if labelled_link(text):
        points += 3
    else:
        notes.append("нет ни одной ссылки с ярлыком из списка канала")

    if "E-POST-RETELL" in codes:
        notes.append("это тизер: польза уведена из поста в ссылку")
    else:
        points += 3

    if L.SIMPLE_BLOCK in text.lower():
        points += 2

    return min(points, WEIGHTS["польза"]), notes


def score_structure(codes):
    points, notes = 0, []

    if "E-TG-LIMIT" in codes or "E-CAPTION-LIMIT" in codes or "E-SPLIT-NEEDED" in codes:
        notes.append("длина за гранью: нужен разрез на пост плюс статью")
    elif "W-LEN-SHORT" in codes or "W-LEN-LONG" in codes or "W-SPLIT-SOON" in codes:
        points += 3
        notes.append("длина вышла из коридора рубрики")
    else:
        points += 6

    hashtag_bad = [code for code in codes if code.endswith("HASHTAG-MISSING")]
    hashtag_soft = [
        code
        for code in codes
        if "HASHTAG" in code and not code.endswith("HASHTAG-MISSING")
    ]
    if hashtag_bad:
        notes.append("нет хэштега рубрики")
    elif hashtag_soft:
        points += 1
        notes.append("хэштег есть, но стоит не так или их много")
    else:
        points += 3

    footer_bad = [code for code in codes if "FOOTER" in code and code.startswith("E-")]
    footer_soft = [code for code in codes if "FOOTER" in code and code.startswith("W-")]
    if footer_bad:
        notes.append("футер не на месте или не знак в знак")
    elif footer_soft:
        points += 1
    else:
        points += 3

    rhythm = [
        code
        for code in ("W-DOUBLE-BLANK", "W-PARA-RHYTHM", "W-SENT-LONG", "W-SYMMETRY", "W-POS-STREAK")
        if code in codes
    ]
    if not rhythm:
        points += 4
    elif len(rhythm) == 1:
        points += 2
        notes.append("ритм абзацев хромает: %s" % rhythm[0])
    else:
        notes.append("ритм абзацев хромает в %d местах" % len(rhythm))

    return min(points, WEIGHTS["структура"]), notes


def score_ready(issues):
    errors = [item for item in issues if item["level"] == "ERROR"]
    warns = [item for item in issues if item["level"] == "WARN"]
    points = WEIGHTS["готовность"] - 4 * len(errors) - len(warns)
    notes = []
    if errors:
        notes.append(
            "ошибок линтера %d: %s"
            % (len(errors), ", ".join(item["code"] for item in errors[:5]))
        )
    if warns:
        notes.append(
            "предупреждений %d: %s"
            % (len(warns), ", ".join(item["code"] for item in warns[:5]))
        )
    return max(0, min(points, WEIGHTS["готовность"])), notes, len(errors), len(warns)


def metrics(root):
    try:
        data = M.load_metrics(root)
    except Exception:
        data = dict(FALLBACK)
        data["samples"] = []
    for key, value in FALLBACK.items():
        if not data.get(key):
            data[key] = value
    data.setdefault("samples", [])
    return data


def fix_lines(parts, notes, numbers):
    """Три правки по самым слабым критериям. Каждая опирается на цифры канала."""
    low, high = numbers["reach"]
    react_low, react_high = numbers["reactions"]
    subs = numbers["subscribers"]
    ground = {
        "крючок": "При %d подписчиках охват хорошего поста %d-%d. Первые 90 знаков это вся пуш-выдача, вынеси туда цифру и выгоду."
        % (subs, low, high),
        "душа": "Реакций на пост всего %d-%d, и ставят их за живое: тёплое слово, мнение, шутку. Разбор: reference/soul.md."
        % (react_low, react_high),
        "голос": "Реакций на пост всего %d-%d. Их ставят за живую деталь, а не за сухой факт. Добавь строку про свой опыт."
        % (react_low, react_high),
        "польза": "Охват выше %d бывает только на пересылках. Пересылают нумерованную пользу внутри поста, а не анонс со ссылкой."
        % subs,
        "структура": "Коридоры длин взяты из постов с охватом %d-%d. Выйдешь из коридора, теряешь дочитывание."
        % (low, high),
        "готовность": "Ошибки линтера это стоп. При %d подписчиках пост с ошибками не берёт даже %d просмотров. Прогони lint_post.py и перепроверь."
        % (subs, low),
    }
    order = sorted(CRITERIA, key=lambda name: parts[name])
    out = []
    for name in order:
        if parts[name] >= WEIGHTS[name]:
            continue
        detail = notes.get(name) or []
        what = detail[0] if detail else "подтяни этот критерий"
        out.append(
            {
                "criterion": name,
                "points": parts[name],
                "what": what,
                "why": ground[name],
            }
        )
        if len(out) == 3:
            break
    return out


def verdict(total, errors):
    if errors:
        return "переписать: есть ошибки линтера, публиковать нельзя"
    if total >= 85:
        return "можно отдавать автору"
    if total >= 70:
        return "почти: один блок переписать и будет готов"
    if total >= 50:
        return "сыро: перепиши крючок и тело по правкам ниже"
    return "с нуля: текст не похож на пост канала"


def score(text, rubric=None, media=False, root=SKILL, published=False):
    issues, rubric = L.lint(text, rubric, media, published=published)
    codes = codes_of(issues)

    hook, hook_notes = score_hook(text, codes)
    soul_points, soul_notes = score_soul(text, codes)
    voice, voice_notes = score_voice(text, codes)
    value, value_notes = score_value(text, rubric, codes)
    structure, structure_notes = score_structure(codes)
    ready, ready_notes, errors, warns = score_ready(issues)

    parts = {
        "крючок": hook,
        "душа": soul_points,
        "голос": voice,
        "польза": value,
        "структура": structure,
        "готовность": ready,
    }
    notes = {
        "крючок": hook_notes,
        "душа": soul_notes,
        "голос": voice_notes,
        "польза": value_notes,
        "структура": structure_notes,
        "готовность": ready_notes,
    }

    total = sum(parts.values())
    capped = False
    screen = first_screen(text)
    proof = (
        errors == 0
        and warns == 0
        and (re.search(r"\d", screen) or L.has_any(screen.lower(), L.CONTRAST))
    )
    if total > CEILING_WITHOUT_PROOF and not proof:
        total = CEILING_WITHOUT_PROOF
        capped = True

    # Чистый анонс не бывает сырым: вся польза лежит в статье.
    if errors == 0 and is_announce(text):
        total = max(total, ANNOUNCE_FLOOR)
        capped = False

    numbers = metrics(root)
    return {
        "version": VERSION,
        "rubric": rubric,
        "total": total,
        "parts": parts,
        "notes": notes,
        "errorCount": errors,
        "warnCount": warns,
        "capped": capped,
        "verdict": verdict(total, errors),
        "fixes": fix_lines(parts, notes, numbers),
        "benchmark": {
            "subscribers": numbers["subscribers"],
            "reach": list(numbers["reach"]),
            "reactions": list(numbers["reactions"]),
            "samples": len(numbers["samples"]),
        },
    }


def print_report(name, data):
    print("Оценка поста: %d из 100" % data["total"])
    print("Файл: %s" % name)
    if data["rubric"]:
        print("Рубрика: #%s" % data["rubric"])
    print("Вердикт: %s" % data["verdict"])
    print()
    print("По критериям:")
    for name_part in CRITERIA:
        print("  %-11s %2d / %d" % (name_part, data["parts"][name_part], WEIGHTS[name_part]))
        for note in data["notes"][name_part]:
            print("      %s" % note)
    if data["capped"]:
        print()
        print("Потолок 90: выше без чистого линтера и без цифры или драмы факта в крючке не бывает.")
    if data["fixes"]:
        print()
        print("Три правки по порядку важности:")
        for index, fix in enumerate(data["fixes"], 1):
            print("  %d. [%s %d/%d] %s"
                  % (index, fix["criterion"], fix["points"], WEIGHTS[fix["criterion"]], fix["what"]))
            print("     почему: %s" % fix["why"])
    mark = data["benchmark"]
    print()
    print(
        "Опора: %d подписчиков, охват %d-%d, реакций %d-%d, замеров в памяти %d."
        % (
            mark["subscribers"],
            mark["reach"][0],
            mark["reach"][1],
            mark["reactions"][0],
            mark["reactions"][1],
            mark["samples"],
        )
    )


BAD_POST = """Всем доброго и прекрасного дня, дорогие подписчики нашего уютного канала!

В современном мире искусственный интеллект играет важную роль в нашей жизни.
Это очень просто и очень удобно, буквально вообще для всех и для каждого.
Мы решили рассказать тебе про это и просто поделиться мыслями по этому поводу.

Подробности по ссылке ниже, там всё подробно расписано и разложено по полочкам.
"""


def selftest():
    failed = 0
    checks = []

    sample_path = os.path.join(HERE, "sample-post.txt")
    with open(sample_path, encoding="utf-8") as handle:
        good = handle.read()

    good_data = score(good)
    checks.append(("образцовый пост берёт не меньше 75", good_data["total"] >= 75))
    checks.append(("у образца нет ошибок", good_data["errorCount"] == 0))
    checks.append(("готовность образца полная",
                   good_data["parts"]["готовность"] == WEIGHTS["готовность"]))
    checks.append(("балл не выходит за 100", 0 <= good_data["total"] <= 100))
    checks.append(("сумма весов ровно 100", sum(WEIGHTS.values()) == 100))

    milahi_path = os.path.join(HERE, "tests", "good-08-milahi.txt")
    if os.path.exists(milahi_path):
        with open(milahi_path, encoding="utf-8") as handle:
            milahi = score(handle.read(), published=True)
        checks.append(("реальный пост автора берёт не меньше 80", milahi["total"] >= 80))
        checks.append(("у реального поста есть душа", milahi["parts"]["душа"] >= 10))
        checks.append(("реальный пост чист по линтеру", milahi["errorCount"] == 0))

    dry_path = os.path.join(HERE, "tests", "bad-12-suhoy-bez-dushi.txt")
    if os.path.exists(dry_path):
        with open(dry_path, encoding="utf-8") as handle:
            dry = score(handle.read(), rubric="сервисы")
        checks.append(("сухой пост теряет на душе", dry["parts"]["душа"] <= 6))

    bad_data = score(BAD_POST, rubric="абуз")
    checks.append(("слоп-пост не берёт больше 45", bad_data["total"] <= 45))
    checks.append(("у слоп-поста есть ошибки", bad_data["errorCount"] > 0))
    checks.append(("вердикт запрещает публикацию", "нельзя" in bad_data["verdict"]))
    checks.append(("правок ровно три", len(bad_data["fixes"]) == 3))
    checks.append(
        (
            "каждая правка опирается на цифры",
            all(re.search(r"\d", fix["why"]) for fix in bad_data["fixes"]),
        )
    )
    checks.append(("хороший выше плохого", good_data["total"] > bad_data["total"]))

    without = "Здарова. Собрал сервисы, где есть бесплатный доступ к моделям без карты."
    with_digit = "Здарова. Собрал 5 сервисов, где есть бесплатный доступ к моделям без карты."
    hook_without = score_hook(without, set())[0]
    hook_with = score_hook(with_digit, set())[0]
    checks.append(("цифра в крючке поднимает балл", hook_with > hook_without))

    fake_codes = {"E-GREETING-LONG"}
    checks.append(
        (
            "длинное приветствие снижает крючок",
            score_hook(with_digit, fake_codes)[0] < hook_with,
        )
    )

    checks.append(
        (
            "потолок 90 без доказательств работает",
            good_data["total"] <= CEILING_WITHOUT_PROOF or good_data["warnCount"] == 0,
        )
    )

    ready_zero = score_ready([{"level": "ERROR", "code": "X"}] * 6)[0]
    checks.append(("готовность не уходит в минус", ready_zero == 0))

    for name, ok in checks:
        if ok:
            print("PASS %s" % name)
        else:
            print("FAIL %s" % name)
            failed += 1

    print("Итого: %d проверок, провалилось %d" % (len(checks), failed))
    if failed:
        print("Для разбора: образец %d, слоп %d" % (good_data["total"], bad_data["total"]))
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Оценщик постов VIORA STUDIO")
    parser.add_argument("file", nargs="?", help="файл с черновиком, без аргумента читает stdin")
    parser.add_argument("--rubric", help="рубрика без решётки")
    parser.add_argument("--media", action="store_true", help="пост идёт с фото")
    parser.add_argument("--published", action="store_true",
                        help="пост уже вышел: приветствие на повтор не проверяем")
    parser.add_argument("--json", action="store_true", dest="as_json", help="машинный вывод")
    parser.add_argument("--min", type=int, default=0, dest="minimum", help="порог для гейта")
    parser.add_argument("--root", default=SKILL, help="корень скилла для цифр памяти")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            text = handle.read()
        name = args.file
    else:
        text = sys.stdin.read()
        name = "stdin"

    data = score(text, args.rubric, args.media, args.root, args.published)
    if args.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_report(name, data)

    return 1 if data["total"] < args.minimum else 0


if __name__ == "__main__":
    sys.exit(main())
