#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заглушка движка SHORTS для тестов слоя Viora (PROMPT-2, раздел 1).

Принимает тот же интерфейс, что настоящий движок:
    python3 fake_engine.py render plan.json --out DIR
    python3 fake_engine.py qa DIR
Ничего не рендерит. Проверяет план по схеме, пишет фиктивный fake.mp4, тайминги
слов по оценке и qa.json с честной пометкой "fake": true.

FAKE_ENGINE_FAIL=duration: первый рендер «длиннее цели», чтобы проверить гейт с повтором.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from vshorts import schema  # noqa: E402
from vshorts.common import speech_seconds  # noqa: E402


def render(plan_path: str, out_dir: str) -> int:
    with open(plan_path, encoding="utf-8") as handle:
        plan = json.load(handle)
    problems = schema.validate(plan, schema.load_schema())
    os.makedirs(out_dir, exist_ok=True)
    if problems:
        print("план не по схеме:\n" + "\n".join(problems), file=sys.stderr)
        return 2
    lang = plan["meta"]["language"]
    speed = float(plan.get("audio", {}).get("voice", {}).get("speed", 1.0))
    words = []
    clock = 0.0
    for scene in plan["scenes"]:
        hint = float(scene.get("x_duration_hint") or speech_seconds(scene.get("say", ""), lang, speed) + 0.4)
        tokens = (scene.get("say") or "").split()
        unit = (hint - 0.3) / max(1, len(tokens))
        t = clock + 0.15
        for token in tokens:
            words.append({"word": token, "start": round(t, 3), "end": round(t + unit * 0.9, 3)})
            t += unit
        clock += hint
    counter = os.path.join(out_dir, ".renders")
    renders = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
    open(counter, "w").write(str(renders))
    if os.environ.get("FAKE_ENGINE_FAIL") == "duration" and renders == 1:
        clock = plan["meta"].get("duration_target", [20, 40])[1] + 5
    with open(os.path.join(out_dir, "fake.mp4"), "wb") as handle:
        handle.write(b"FAKE VIDEO: the real engine renders here")
    json.dump(words, open(os.path.join(out_dir, "words.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"fake": True, "duration": round(clock, 2), "plan": os.path.abspath(plan_path)},
              open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8"))
    print("fake render: %.1f s, %d words" % (clock, len(words)))
    return 0


def qa(out_dir: str) -> int:
    result = json.load(open(os.path.join(out_dir, "result.json"), encoding="utf-8"))
    plan = json.load(open(result["plan"], encoding="utf-8"))
    target = plan["meta"].get("duration_target", [20, 40])
    layout = plan["layout"]
    used = sum(layout.get(k, {}).get("height_pct", 0) for k in ("top", "bottom")
               if (k == "top" and layout["mode"] in ("three", "top_center"))
               or (k == "bottom" and layout["mode"] in ("three", "center_bottom")))
    qr = [c for c in layout.get("cta_in_center", []) if c.get("kind") == "qr"]
    checks = [
        {"id": "duration", "ok": target[0] - 2 <= result["duration"] <= target[1] + 0.5,
         "detail": "%.1f s, target %s" % (result["duration"], target)},
        {"id": "center_55", "ok": 100 - used >= 55, "detail": "center %d%%" % (100 - used)},
        {"id": "captions", "ok": plan.get("captions", {}).get("enabled", True), "detail": "word captions"},
        {"id": "qr_planned", "ok": bool(qr), "detail": "QR flash in plan (fake engine cannot decode)"},
        {"id": "no_dashes", "ok": not re.search("[\u2014\u2013]", json.dumps(plan, ensure_ascii=False)), "detail": "rule zero"},
    ]
    passed = all(c["ok"] for c in checks)
    report = {"fake": True, "passed": passed, "checks": checks,
              "not_checked": ["first_frame", "motion", "safe_zone_pixels", "qr_decode", "lufs", "anti_slop_pixels"]}
    json.dump(report, open(os.path.join(out_dir, "qa.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["render"] and len(argv) >= 4 and argv[2] == "--out":
        return render(argv[1], argv[3])
    if argv[:1] == ["qa"] and len(argv) >= 2:
        return qa(argv[1])
    print("usage: fake_engine.py render plan.json --out DIR | qa DIR", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
