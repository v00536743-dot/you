#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Линтер упаковки ролика: названия, описание, закреп, подпись TikTok.

    python3 tools/lint_video_meta.py out/reel/meta.json
    python3 tools/lint_video_meta.py out/reel/            папка пакета, берёт meta.json
    python3 tools/lint_video_meta.py meta.json --json
    python3 tools/lint_video_meta.py --selftest

Правила: 5-7 названий от громкого к консервативному, до 100 знаков, не больше
одного эмодзи, 3-6 хэштегов, капс только в громких, ровно один рекомендованный,
ОДНО описание с 1-3 тегами сверху и ссылкой автора, закреп до трёх строк,
TikTok до пяти тегов, длинных тире нет нигде. Коды в viora-shorts/vshorts/metalint.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "viora-shorts"))

from vshorts import metalint  # noqa: E402

VERSION = "1.0.0"


def run_selftest() -> int:
    failed = 0
    cases = metalint.selftest_cases()
    for name, data, code in cases:
        found = metalint.lint(data)
        codes = [i["code"] for i in found if i["level"] == "ERROR"]
        ok = (not codes) if code is None else (code in codes)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else ": %s" % codes))
        failed += 0 if ok else 1
    print("Итого: %d проверок линтера упаковки, провалилось %d" % (len(cases), failed))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Линтер названий и описаний ролика")
    parser.add_argument("path", nargs="?")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print("lint_video_meta.py %s" % VERSION)
        return 0
    if args.selftest:
        return run_selftest()
    if not args.path:
        parser.error("нужен путь к meta.json или папке пакета")
    path = os.path.join(args.path, "meta.json") if os.path.isdir(args.path) else args.path
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    issues = metalint.lint(data)
    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        for item in issues:
            print("%s %s: %s" % (item["level"], item["code"], item["message"]))
        bad = metalint.errors(issues)
        print("Чисто. Упаковку можно отдавать автору." if not bad else
              "Ошибок %d: правь и запускай снова." % len(bad))
    return 1 if metalint.errors(issues) else 0


if __name__ == "__main__":
    sys.exit(main())
