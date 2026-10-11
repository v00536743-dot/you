#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ролики VIORA STUDIO: сырьё автора -> план -> движок SHORTS -> пакет к публикации.

Главная команда (автор пишет «с этим делай ролик, а не пост»):
    python3 tools/reel.py farm post.txt
    python3 tools/reel.py farm "https://learn-anything.xyz/ https://www.cadlookup.com/"
    python3 tools/reel.py farm film.html --speed "0-4:1,4-20:2,20-24:0.5" --sound page
    python3 tools/reel.py farm post.txt --lang en --script script-en.json

Шаги по отдельности:
    python3 tools/reel.py intake post.txt          что за сырьё, какие сайты открываются
    python3 tools/reel.py script post.txt          заготовка script.json для правки голосом
    python3 tools/reel.py check out/x/plan.json     план по схеме и правилам
    python3 tools/reel.py prefs missing             вопросы одним сообщением
    python3 tools/reel.py prefs set language=en     ответ автора
    python3 tools/reel.py prefs skip                пропустить, поставить умолчания, напоминать
    python3 tools/reel.py prefs remind              одна строка про незаполненное
    python3 tools/reel.py prefs reset               «сбрось настройки»
    python3 tools/reel.py prefs choose-title "..."  запомнить выбор автора
    python3 tools/reel.py log out/x                 записать вышедший ролик в журнал
    python3 tools/reel.py due                       какие замеры пора снять
    python3 tools/reel.py measure NAME 24h shown=1200 viewed_pct=71 avg_pct=64 likes=30 subs=4 clicks=9
    python3 tools/reel.py experiment "первый кадр" "результат в кадре даст больше viewed"
    python3 tools/reel.py doctor                    что есть для роликов
    python3 tools/reel.py selftest                  все тесты модуля

Коды выхода: 0 готово, 1 ошибка, 3 нужны ответы автора (вопросы напечатаны).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
MOD = os.path.join(SKILL, "viora-shorts")
sys.path.insert(0, MOD)

from vshorts import engine, farm, intake, journal, plan as planner, prefs, probe, schema, script  # noqa: E402

VERSION = "1.0.0"


def _source(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    return value


def _links(pairs):
    out = {}
    for pair in pairs or []:
        name, _, url = pair.partition("=")
        if name and url:
            out[name.strip()] = url.strip()
    return out


def cmd_farm(args) -> int:
    try:
        summary = farm.run(_source(args.source), args.out, lang=args.lang, assume_defaults=args.defaults,
                           offline=args.offline, engine_override=args.engine, script_path=args.script,
                           links=_links(args.link), part=args.part, speed_spec=args.speed or "",
                           sound=args.sound, video_url=args.video_url, post_url=args.post_url,
                           write_log=args.log, retry_blocked=args.retry_blocked)
    except farm.FarmStop as stop:
        print(stop.message)
        for key in ("issues",):
            for item in stop.details.get(key, []):
                print("  %s %s: %s" % (item["level"], item["code"], item["message"]))
        for row in stop.details.get("sites", []):
            print("  " + row)
        if stop.details.get("out"):
            print("Папка: %s" % stop.details["out"])
        return 3 if stop.status == "ask" else 1
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(open(os.path.join(summary["out"], "report.md"), encoding="utf-8").read())
        print("Папка с пакетом: %s" % summary["out"])
    return 0 if summary["status"] in ("ready", "plan-ready") else 1


def cmd_intake(args) -> int:
    raw = intake.detect(_source(args.source), _links(args.link))
    print("Сырьё: %s" % raw.kind)
    if raw.hook:
        print("Крючок поста: %s" % raw.hook)
    if raw.rubric:
        print("Рубрика: #%s" % raw.rubric)
    if raw.items:
        checked = probe.check_items(raw.items, offline=args.offline)
        print("\n".join(probe.report_lines(checked)))
        parts = probe.select(checked)
        for index, part in enumerate(parts, 1):
            print("Часть %d: %s" % (index, ", ".join(c.item.name for c in part)))
    for note in raw.notes:
        print(note)
    return 0


def cmd_script(args) -> int:
    raw = intake.detect(_source(args.source), _links(args.link))
    store = prefs.effective(prefs.load(), args.lang)
    lang = store["language"]
    handle = store["links"].get("handle") or prefs.HANDLE
    if raw.kind == "html":
        from vshorts import html_adapter
        built = script.build_html(html_adapter.inspect(raw.path), lang, [], handle)
    else:
        checked = probe.check_items(raw.items, offline=True)
        parts = probe.select(checked)
        if not parts:
            print("нет пунктов с живыми ссылками")
            return 1
        items = [c.item for c in parts[(args.part or 1) - 1]]
        try:
            built = script.build(raw, items, lang, args.part or 1, len(parts), handle)
        except ValueError:
            built = script.build(raw, items, "ru", args.part or 1, len(parts), handle)
            built.lang = lang
            print("Заготовка на русском: перепиши реплики на %s и проверь: reel.py farm ... --script FILE" % lang,
                  file=sys.stderr)
    text = json.dumps(built.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        print("Заготовка: %s" % args.out)
    else:
        print(text)
    for item in script.lint(built, raw.text):
        print("%s %s: %s" % (item["level"], item["code"], item["message"]), file=sys.stderr)
    return 0


def cmd_check(args) -> int:
    data = json.load(open(args.plan, encoding="utf-8"))
    store = prefs.effective(prefs.load())
    qr = store["links"].get("telegram") if store.get("qr", True) else None
    issues = schema.full_check(data, expect_qr_url=qr if args.qr else None, known_presets=planner.known_presets())
    for item in issues:
        print("%s %s: %s" % (item["level"], item["code"], item["message"]))
    bad = [i for i in issues if i["level"] == "ERROR"]
    print("План чистый." if not bad else "Ошибок в плане: %d" % len(bad))
    return 1 if bad else 0


def cmd_prefs(args) -> int:
    store = prefs.load()
    action = args.action
    if action == "show":
        print(json.dumps(store, ensure_ascii=False, indent=2))
    elif action == "missing":
        text = prefs.questions_message(store)
        print(text or "Настройки на месте: %s" % summary_line(store))
    elif action == "set":
        for pair in args.values:
            key, _, value = pair.partition("=")
            try:
                print(prefs.set_value(store, key, value))
            except ValueError as error:
                print("не записал %s: %s" % (key, error))
                return 1
        prefs.save(store)
    elif action == "skip":
        done = prefs.skip(store, args.values or None)
        prefs.save(store)
        print("Пропущено, ставлю умолчания и напомню: %s" % ", ".join(done) if done else "Пропускать нечего.")
    elif action == "remind":
        print(prefs.reminder(store) or "Всё заполнено.")
    elif action == "reset":
        prefs.reset()
        print("Настройки роликов сброшены. Ссылки снова из brand.md.")
    elif action in ("choose-title", "reject-title"):
        for title in args.values:
            prefs.remember_title(store, title, chosen=action == "choose-title")
        prefs.save(store)
        print("Запомнил.")
    return 0


def summary_line(store) -> str:
    eff = prefs.effective(store)
    return "язык %s, площадки %s, раскладка %s, стиль %s, QR %s, голос %s" % (
        eff["language"], ", ".join(eff["platforms"]), eff.get("layout") or "по типу ролика", eff["brand"]["preset"],
        "да" if eff["qr"] else "нет", eff["voice"]["voice"])


def cmd_log(args) -> int:
    summary = json.load(open(os.path.join(args.folder, "summary.json"), encoding="utf-8"))
    title = args.title or summary.get("recommended_title", "")
    store = prefs.load()
    if args.title:
        prefs.remember_title(store, args.title, True)
        prefs.save(store)
    result = journal.add(summary["name"], title, prefs.effective(store)["platforms"], summary["seconds"], args.date)
    print(result.get("row") or result.get("note"))
    if result.get("h24"):
        print("Замеры: %s (сутки) и %s (неделя). Напомню командой reel.py due." % (result["h24"], result["d7"]))
    return 0


def cmd_due(args) -> int:
    rows = journal.due(args.today)
    if not rows:
        print("Замеров на сегодня нет.")
        return 0
    for row in rows:
        print("Пора снять замер %s: %s (%s), срок был %s" % (row["window"], row["name"], row["title"], row["date"]))
    print("Цифры из Studio: показано в ленте, остались (viewed vs swiped away), средний %, лайки, подписки, переходы.")
    return 0


def cmd_measure(args) -> int:
    values = dict(pair.split("=", 1) for pair in args.values if "=" in pair)
    print(journal.measure(args.name, args.window, values, args.date))
    print("Следующий эксперимент: %s" % journal.suggest(values))
    return 0


def cmd_experiment(args) -> int:
    print(journal.add_experiment(args.change, args.hypothesis, args.reels or "-"))
    return 0


def cmd_doctor(args) -> int:
    from vshorts import cover
    rows = [
        ("питон", sys.version_info >= (3, 9), sys.version.split()[0]),
        ("движок SHORTS", bool(engine.find()), engine.version()),
        ("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "нет: кадр для обложки не вырезать"),
        ("Pillow для обложек", cover.available(), "есть" if cover.available() else "нет: pip install Pillow, иначе только промпт"),
        ("генератор картинок", prefs.image_generator()["available"], ", ".join(prefs.image_generator()["keys"]) or "нет ключей, пишу промпт"),
        ("шрифты бренда", os.path.exists(os.path.join(MOD, "brand", "fonts", "Montserrat-ExtraBold.ttf")), "Montserrat OFL"),
        ("настройки роликов", not prefs.missing(prefs.load()), prefs.questions_message(prefs.load()) and "есть незаданные вопросы" or "на месте"),
    ]
    for name, ok, detail in rows:
        print("  %-22s %-4s %s" % (name, "ок" if ok else "нет", detail))
    return 0


def cmd_selftest(args) -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", os.path.join(MOD, "tests"), "-t", os.path.join(MOD, "tests")]
                          + (["-v"] if args.verbose else []), cwd=MOD, env=env)
    return proc.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ролики VIORA STUDIO")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("farm", help="сырьё -> готовый пакет ролика")
    p.add_argument("source", help="файл, текст, ссылки или - для stdin")
    p.add_argument("--out", default=os.path.join(SKILL, "out", "reels"))
    p.add_argument("--lang")
    p.add_argument("--defaults", action="store_true", help="не спрашивать, взять умолчания и напомнить")
    p.add_argument("--offline", action="store_true", help="не ходить в сеть, верить реестру сайтов")
    p.add_argument("--engine", help="путь к движку или fake")
    p.add_argument("--script", help="script.json от модели")
    p.add_argument("--link", action="append", help="имя=ссылка для пункта без адреса")
    p.add_argument("--part", type=int)
    p.add_argument("--speed", help="карта скоростей HTML: 0-5:1,5-12:2.5")
    p.add_argument("--sound", choices=("page", "sfx", "music", "mute"))
    p.add_argument("--video-url")
    p.add_argument("--post-url")
    p.add_argument("--log", action="store_true", help="записать в журнал, если ролик готов")
    p.add_argument("--retry-blocked", action="store_true", help="заново попробовать сайты, закрытые в прошлый раз")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_farm)

    p = sub.add_parser("intake")
    p.add_argument("source")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--link", action="append")
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("script")
    p.add_argument("source")
    p.add_argument("--lang")
    p.add_argument("--part", type=int)
    p.add_argument("--out")
    p.add_argument("--link", action="append")
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("check")
    p.add_argument("plan")
    p.add_argument("--qr", action="store_true", help="требовать QR на ссылку из настроек")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("prefs")
    p.add_argument("action", choices=("show", "missing", "set", "skip", "remind", "reset", "choose-title", "reject-title"))
    p.add_argument("values", nargs="*")
    p.set_defaults(func=cmd_prefs)

    p = sub.add_parser("log")
    p.add_argument("folder")
    p.add_argument("--title")
    p.add_argument("--date")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("due")
    p.add_argument("--today")
    p.set_defaults(func=cmd_due)

    p = sub.add_parser("measure")
    p.add_argument("name")
    p.add_argument("window", choices=("24h", "7d"))
    p.add_argument("values", nargs="*")
    p.add_argument("--date")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("experiment")
    p.add_argument("change")
    p.add_argument("hypothesis")
    p.add_argument("--reels")
    p.set_defaults(func=cmd_experiment)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    p = sub.add_parser("selftest")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    if args.version:
        print("reel.py %s" % VERSION)
        return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
