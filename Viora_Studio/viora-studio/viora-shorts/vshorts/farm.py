"""Режим «ферма»: «с этим делай ролик, а не пост» одной командой.

Сырьё -> проверка сайтов -> сценарий -> план -> движок и QA-гейт -> названия,
описание, закреп, TikTok, .srt -> обложки или промпт -> анонс в канал ->
чек-лист из 20 пунктов -> журнал и план замера -> напоминание о пропущенном.

Вопросов не задаём, если настройки сохранены. Нет настроек: возвращаем вопросы
одним сообщением (или берём умолчания с флагом --defaults и напоминаем потом).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from . import announce, cover, engine as eng, html_adapter, intake, journal, meta, metalint
from . import plan as planner, prefs as prefs_mod, probe, schema, script as scripter
from .common import fix_dashes, skill_root, slug, write_json, write_text, words

MAX_ATTEMPTS = 3
VIDEO_PLACEHOLDER = "PASTE_VIDEO_URL"


class FarmStop(Exception):
    def __init__(self, status: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


def text_script(raw: intake.Raw, lang: str, handle: str, speed: float) -> scripter.Script:
    """Адаптер text: тема или текст без пунктов. Крючок, до четырёх мыслей, призыв."""
    parts = scripter.sentences(raw.text)
    if not parts:
        raise FarmStop("empty", "в сырье нет текста")
    beats = [scripter.Beat("hook", "hook", scripter.compress(parts[0], 14),
                           " ".join(parts[0].split()[:4]).upper().rstrip(".,:!"), "главная мысль сразу")]
    for index, sentence in enumerate(parts[1:5], 1):
        beats.append(scripter.Beat("idea-%d" % index, "chapter", scripter.compress(sentence, 18), "",
                                   "одна мысль на сцену"))
    cta = ("Подробности в канале %s, ссылка в закрепе." % handle) if lang == "ru" else \
        ("More on the %s channel, link in the pinned comment." % handle)
    beats.append(scripter.Beat("cta", "cta", cta, "ССЫЛКА В ЗАКРЕПЕ" if lang == "ru" else "LINK IN PINNED COMMENT",
                               "один призыв после пользы"))
    built = scripter.Script(lang=lang, beats=beats)
    scripter.retime(built, speed)
    return built


def checklist(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """20 пунктов из research/click-and-watch.md раздел 9. auto: проверил код, engine: движок, manual: глаза."""
    qa_checks = {c.get("id", ""): c for c in ((ctx.get("qa") or {}).get("checks") or [])}
    fake = bool((ctx.get("qa") or {}).get("fake"))
    script_codes = {i["code"] for i in ctx.get("script_issues", [])}
    plan_codes = {i["code"] for i in ctx.get("plan_issues", [])}
    meta_codes = {i["code"] for i in ctx.get("meta_issues", [])}

    def eng_state(*keys: str) -> str:
        if not ctx.get("rendered"):
            return "нет рендера"
        hits = [c for cid, c in qa_checks.items() if any(k in cid for k in keys)]
        if not hits:
            return "движок не проверял" + (" (заглушка)" if fake else "")
        return "да" if all(c.get("ok", c.get("passed")) for c in hits) else "НЕТ"

    def mine(ok: bool) -> str:
        return "да" if ok else "НЕТ"

    covers_ok = ctx.get("covers") and all(all(c["ok"] for c in r["checks"]) for r in ctx["covers"])
    rows = [
        ("1", "Первый кадр уже интересный", "engine", eng_state("first")),
        ("2", "Первая фраза без приветствия, сразу результат", "auto",
         mine(not script_codes & {"E-GREETING", "E-FILLER", "E-HOOK-LONG"})),
        ("3", "Идея читается в миниатюре и без звука", "manual", "смотри контактный лист"),
        ("4", "Название честное, до 100 знаков, одно эмодзи", "auto",
         mine(not {c for c in meta_codes if c.startswith("E-TITLE")})),
        ("5", "Обложка: один фокус, 3-5 слов, 320 px, контраст", "auto",
         mine(bool(covers_ok)) if ctx.get("covers") else "только промпт (нет Pillow)"),
        ("6", "Событие каждые 2-3 секунды", "auto+engine",
         mine("W-STILL" not in plan_codes) + ", движок: " + eng_state("motion", "event")),
        ("7", "Нет паузы дольше секунды", "engine", eng_state("pause", "silence", "dead")),
        ("8", "Обещание из начала выполнено", "auto+manual",
         mine("E-NUMBER" not in script_codes) + " по цифрам, смысл проверь глазами"),
        ("9", "Нет прощания, петля или часть 2", "auto", mine(not script_codes & {"E-FAREWELL"} and ctx.get("loop", False))),
        ("10", "Понятно без звука, субтитры есть", "auto+manual",
         mine("W-CAPTIONS-OFF" not in plan_codes) + ", перескажи ролик без звука"),
        ("11", "Один призыв после пользы", "auto", mine(not script_codes & {"E-CTA-COUNT", "E-CTA-EARLY"})),
        ("12", "Ссылка в кадре дважды, QR сканируется", "auto+engine",
         mine(not plan_codes & {"E-QR-MISSING", "E-QR-URL", "E-QR-NO-TEXT"}) + ", декодер: " + eng_state("qr_decode", "decode")),
        ("13", "Закреп и описание готовы", "auto",
         mine(not {c for c in meta_codes if c.startswith(("E-DESC", "E-PINNED"))})),
        ("14", "Профиль канала готов", "manual", "напомни автору: аватар, шапка, одна ссылка, закреп"),
        ("15", "Всё важное в рабочей зоне платформы", "engine", eng_state("safe")),
        ("16", "Нет слопа: градиент, свечение, шрифт по умолчанию", "auto+engine",
         mine(not plan_codes & {"E-FONT-DEFAULT", "E-COLORS", "E-MONO-COLOR", "E-TOP-SLOP"}) + ", кадры: " +
         eng_state("slop", "glow", "gradient")),
        ("17", "Язык верный, длинных тире нет", "auto",
         mine(not (script_codes | plan_codes | meta_codes) & {"E-LANG", "E-DASH"})),
        ("18", "Громкость около -14 LUFS", "engine", eng_state("lufs", "loud")),
        ("19", "Пометка «изменённый или синтетический контент»", "manual",
         "озвучка синтезатором обычно не требует, реалистичных подделок в ролике нет: проверь при загрузке"),
        ("20", "Ролик отличается от прошлых", "auto", ctx.get("distinct", "нет журнала")),
    ]
    return [{"n": n, "what": what, "who": who, "state": state} for n, what, who, state in rows]


def distinct(hook: str, title: str, root: Optional[str]) -> str:
    """Различимость: новый крючок и название не должны повторять прошлые почти слово в слово."""
    path = os.path.join(skill_root(root), "memory", journal.LOG)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return "да (журнал пуст)"
    mine = set(w.lower() for w in words(title.split("#")[0]))
    worst = 0.0
    for row in journal._rows(text):
        other = set(w.lower() for w in words(row[2].split("#")[0]))
        if mine and other:
            worst = max(worst, len(mine & other) / len(mine | other))
    return "да (похожесть %.0f%%)" % (worst * 100) if worst < 0.7 else "НЕТ: название почти как у прошлого ролика"


def _extract_frame(video: Optional[str], out: str) -> Optional[str]:
    if not video or not shutil.which("ffmpeg"):
        return None
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", video, "-frames:v", "1", out],
                       check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out if os.path.exists(out) else None
    except (subprocess.SubprocessError, OSError):
        return None


def _render_gate(cmd: List[str], plan: Dict[str, Any], plan_path: str, out_dir: str,
                 script: scripter.Script, prefs: Dict[str, Any], build_plan: Any) -> Dict[str, Any]:
    """Рендер и QA с повтором. Длину чиним сами, остальное отдаём модели с причинами."""
    attempts: List[Dict[str, Any]] = []
    speed = float((prefs.get("voice") or {}).get("speed", 1.05))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        render_dir = os.path.join(out_dir, "render")
        step = eng.render(cmd, plan_path, render_dir)
        if step["code"] != 0:
            attempts.append({"attempt": attempt, "stage": "render", "code": step["code"], "err": step["err"][-600:]})
            break
        check = eng.qa(cmd, render_dir)
        failed = eng.failed_checks(check["report"])
        attempts.append({"attempt": attempt, "stage": "qa", "passed": check["passed"],
                         "failed": [c.get("id") for c in failed]})
        if check["passed"]:
            return {"passed": True, "attempts": attempts, "render": step, "qa": check["report"], "plan": plan}
        ids = " ".join(str(c.get("id", "")) for c in failed)
        if "duration" in ids and attempt < MAX_ATTEMPTS:
            real = float(((step.get("result") or {}).get("duration")) or 0)
            target = plan["meta"].get("duration_target", [20, 40])
            if real > target[1]:
                speed = min(1.25, speed + 0.08)
            elif real and real < target[0]:
                speed = max(0.9, speed - 0.08)
            prefs.setdefault("voice", {})["speed"] = round(speed, 2)
            scripter.retime(script, speed)
            plan = build_plan()
            write_json(plan_path, plan)
            continue
        return {"passed": False, "attempts": attempts, "render": step, "qa": check["report"], "plan": plan}
    return {"passed": False, "attempts": attempts, "render": None, "qa": None, "plan": plan}


def run(source: str, out_root: str, *, root: Optional[str] = None, lang: Optional[str] = None,
        assume_defaults: bool = False, offline: bool = False, engine_override: Optional[str] = None,
        script_path: Optional[str] = None, links: Optional[Dict[str, str]] = None, part: Optional[int] = None,
        speed_spec: str = "", sound: Optional[str] = None, video_url: Optional[str] = None,
        post_url: Optional[str] = None, write_log: bool = False, today: Optional[str] = None,
        fetch: Any = None, save_prefs: bool = True, retry_blocked: bool = False) -> Dict[str, Any]:
    store = prefs_mod.load(root)
    asked = prefs_mod.missing(store)
    if asked and not assume_defaults:
        raise FarmStop("ask", prefs_mod.questions_message(store), {"missing": asked})
    if asked:
        prefs_mod.skip(store, asked)
    if save_prefs:
        prefs_mod.save(store, root)
    eff = prefs_mod.effective(store, lang)
    language = eff["language"]
    voice_speed = float(eff["voice"].get("speed", 1.05))
    handle = eff["links"].get("handle") or prefs_mod.HANDLE
    raw = intake.detect(source, links, root)
    ctx: Dict[str, Any] = {"kind": raw.kind, "lang": language}
    site_report: List[str] = []
    dropped: List[str] = []
    html_info = None
    chosen_items: List[Dict[str, Any]] = []
    parts_total = 1
    part_no = part or 1
    noun = "находка" if "находк" in (raw.hook or "").lower() else "сайт"

    if script_path:
        with open(script_path, encoding="utf-8") as handle_file:
            built = scripter.Script.from_dict(json.load(handle_file))
        language = built.lang
        eff = prefs_mod.effective(store, language)
        chosen_items = [b.item for b in built.beats if b.kind == "item" and b.item]
        part_no, parts_total = built.part, built.parts
        voice_speed = float(eff["voice"].get("speed", 1.05))
        if raw.kind in ("post", "links") and raw.items:
            # Сценарий написала модель, но отчёт о сайтах автору всё равно нужен.
            checked = probe.check_items(raw.items, fetch=fetch, offline=offline, root=root, retry_blocked=retry_blocked)
            site_report = probe.report_lines(checked)
            dropped = [c.item.name for c in checked if c.verdict != "берём"]
        if raw.kind == "html":
            html_info = html_adapter.inspect(raw.path)
            scripter.retime_html(built, html_adapter.parse_speed(speed_spec), voice_speed)
        else:
            scripter.retime(built, voice_speed)
    if raw.kind in ("post", "links") and not script_path:
        checked = probe.check_items(raw.items, fetch=fetch, offline=offline, root=root, retry_blocked=retry_blocked)
        site_report = probe.report_lines(checked)
        dropped = [c.item.name for c in checked if c.verdict != "берём"]
        parts = probe.select(checked, root=root)
        if not parts:
            raise FarmStop("no-sites", "ни один сайт не открылся, ролик не из чего собрать",
                           {"sites": site_report})
        parts_total = len(parts)
        if part_no > parts_total:
            raise FarmStop("bad-part", "частей всего %d" % parts_total)
        chosen = [c.item for c in parts[part_no - 1]]
        chosen_items = [i.to_dict() for i in chosen]
        built = scripter.build(raw, chosen, language, part_no, parts_total, handle, voice_speed, root, noun)
    elif raw.kind == "html" and not script_path:
        html_info = html_adapter.inspect(raw.path)
        target = [25.0, 60.0] if "youtube" not in eff["platforms"] or len(eff["platforms"]) > 1 else [60.0, 600.0]
        built = scripter.build_html(html_info, language, html_adapter.parse_speed(speed_spec), handle,
                                    voice_speed, target)
    elif raw.kind == "text" and not script_path:
        built = text_script(raw, language, handle, voice_speed)
    elif raw.kind == "video" and not script_path:
        raise FarmStop("video", "длинное видео режет движок (адаптер video): дай ссылку движку напрямую "
                       "или пришли текст, по нему соберу сценарий")
    if html_info is not None:
        ctx["html"] = html_info.to_dict()

    facts_text = raw.text + " " + (html_info.facts_text() if html_info else "")
    script_issues = scripter.lint(built, facts_text)
    ctx["script_issues"] = script_issues
    name = slug((raw.hook or (html_info.title if html_info else "") or built.beats[0].on_screen))
    if parts_total > 1:
        name = "%s-part-%d" % (name[:40].strip("-"), part_no)
    if language != "ru":
        name += "-" + language
    out_dir = os.path.join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, "script.json"), built.to_dict())
    write_text(os.path.join(out_dir, "script.md"), scripter.to_markdown(built))
    if site_report:
        write_text(os.path.join(out_dir, "sites.md"), "# Проверка сайтов\n\n" + "\n".join(site_report) + "\n")
    if scripter.errors(script_issues):
        raise FarmStop("script", "сценарий не прошёл проверку: правь script.json и запускай с --script",
                       {"issues": script_issues, "out": out_dir})

    sound_mode = sound or (store.get("html") or {}).get("sound") or "page"
    speed_map = html_adapter.parse_speed(speed_spec)

    def build_plan() -> Dict[str, Any]:
        return planner.build(built, eff, raw, html_info=html_info, sound=sound_mode, speed_map=speed_map,
                             base_dir=out_dir, root=root)

    plan = build_plan()
    for note in plan["x_viora"]["pending"]:
        if note not in store.get("pending", []):
            store.setdefault("pending", []).append(note)
    if save_prefs:
        prefs_mod.save(store, root)
    plan_path = os.path.join(out_dir, "plan.json")
    write_json(plan_path, plan)
    qr_url = eff["links"].get("telegram") if eff.get("qr", True) else None
    plan_issues = schema.full_check(plan, expect_qr_url=qr_url, known_presets=planner.known_presets(root), root=root)
    ctx["plan_issues"] = plan_issues
    if schema_errors := [i for i in plan_issues if i["level"] == "ERROR"]:
        raise FarmStop("plan", "план не прошёл проверку", {"issues": schema_errors, "out": out_dir})
    ctx["loop"] = bool(plan["meta"].get("loop")) and (
        plan["scenes"][-1]["source"].get("ref") == plan["scenes"][0]["source"].get("ref") or part_no < parts_total)

    cmd = eng.find(root, engine_override)
    gate: Dict[str, Any] = {"passed": False, "attempts": [], "render": None, "qa": None}
    if cmd:
        gate = _render_gate(cmd, plan, plan_path, out_dir, built, eff, build_plan)
        plan = gate.get("plan", plan)
        ctx["rendered"] = bool(gate.get("render") and gate["render"].get("video"))
        ctx["qa"] = gate.get("qa")
    else:
        ctx["rendered"] = False

    facts = meta.facts_from(chosen_items, language, "бесплатн" in facts_text.lower() or "free" in facts_text.lower(),
                            part_no, parts_total, noun)
    if html_info is not None and not chosen_items:
        tags = ["#html", "#javascript", "#анимация" if language == "ru" else "#animation"]
        if html_info.has_three:
            tags.append("#threejs")
        facts = {"lang": language, "count": 1, "names": [html_info.title], "free": False,
                 "labels": [], "topic_tags": tags, "base_tags": ["#код" if language == "ru" else "#coding"],
                 "part": part_no, "parts": parts_total, "noun": "сайт", "leads": [], "urls": []}
        kb = html_info.size_kb
        sound_word = ("ЗВУК" if language == "ru" else "SOUND") if (html_info.has_webaudio or html_info.has_media) else "CANVAS"
        facts["cover"] = {
            "kicker": " · ".join(["HTML", "JS", sound_word]),
            "headline": html_info.title.upper()[:22],
            "plate": "ОДИН ФАЙЛ" if language == "ru" else "ONE FILE",
            "number": kb, "rest": "КБ" if language == "ru" else "KB",
        }
    package = meta.package(facts, eff["links"], store.get("title_style"), post_url)
    if html_info is not None and not chosen_items:
        package["titles"] = html_titles(html_info, language, package["hashtags"]["title"])
    meta_issues = metalint.lint(package)
    ctx["meta_issues"] = meta_issues
    write_json(os.path.join(out_dir, "meta.json"), package)
    write_text(os.path.join(out_dir, "titles.md"), meta.titles_markdown(package))
    write_text(os.path.join(out_dir, "description.txt"), package["description"])
    write_text(os.path.join(out_dir, "pinned.txt"), package["pinned"])
    write_text(os.path.join(out_dir, "tiktok.txt"), package["tiktok"])
    words_timed = (gate.get("render") or {}).get("words") if gate.get("render") else None
    if words_timed:
        srt = meta.srt_from_words(words_timed, built.subs)
        srt_note = "тайминги слов от заглушки движка" if (ctx.get("qa") or {}).get("fake") else "тайминги слов от движка"
    else:
        srt = meta.srt_from_script([b.to_dict() for b in built.beats], built.subs)
        srt_note = "оценка по длине реплик: точный .srt даст движок"
    write_text(os.path.join(out_dir, "captions.srt"), srt)

    tokens = planner.brand_tokens((eff.get("brand") or {}).get("preset", "viora"), root)
    write_text(os.path.join(out_dir, "cover-prompt.txt"),
               cover.prompt(facts, tokens, (eff.get("brand") or {}).get("register", "minimal")))
    covers: List[Dict[str, Any]] = []
    fake = bool((ctx.get("qa") or {}).get("fake"))
    hero: Optional[str] = None
    if cover.available():
        video = ((gate.get("render") or {}).get("video")) if gate.get("render") else None
        if video and not fake:
            hero = _extract_frame(video, os.path.join(out_dir, "frame.png"))
        if not hero and not offline:
            from . import shot
            targets = [i["url"] for i in chosen_items if i.get("url")]
            if html_info is not None and not targets:
                targets = ["file://" + html_info.path]
            hero = shot.best(targets, os.path.join(out_dir, "shots")) if targets else None
        covers = cover.render_set(facts, tokens, out_dir, shot=hero, root=root)
    ctx["covers"] = covers

    seconds = scripter.total(built)
    if gate.get("render") and (gate["render"].get("result") or {}).get("duration"):
        seconds = float(gate["render"]["result"]["duration"])
    yt = eff["links"].get("youtube") or "https://www.youtube.com/@badVIno-VS"
    ru_facts = meta.facts_from(chosen_items, "ru", facts["free"], part_no, parts_total, noun) if chosen_items else \
        dict(facts, names=[html_info.title] if html_info else facts["names"])
    ru_facts["labels_ru"] = ru_facts.get("labels", [])
    # Ссылки на ролик до загрузки нет: метка вместо адреса канала, её меняет reel.py announce.
    url = video_url or VIDEO_PLACEHOLDER
    if html_info is not None and not chosen_items:
        post, post_issues = announce.best_html(html_info, seconds, url, root)
    else:
        post, post_issues = announce.best(ru_facts, seconds, url, dropped, root)
    write_text(os.path.join(out_dir, "announce.txt"), post)
    ctx["announce_issues"] = post_issues

    recommended = next((t["text"] for t in package["titles"] if t.get("recommended")), "")
    ctx["distinct"] = distinct(built.beats[0].say, recommended, root)
    rows = checklist(ctx)
    reminder = prefs_mod.reminder(store)
    image_gen = prefs_mod.image_generator()
    # Блокируют только ошибки. Предупреждения линтеров идут в отчёт, выдачу не держат.
    blocking = metalint.errors(meta_issues) or [i for i in post_issues if i["level"] == "ERROR"]
    if blocking:
        status = "needs-fix"
    elif gate.get("passed") and not fake:
        status = "ready"
    elif ctx.get("rendered") and not fake:
        status = "rendered-qa-failed"
    else:
        status = "plan-ready"
    summary = {
        "status": status,
        "out": out_dir, "name": name, "kind": raw.kind, "lang": language, "part": part_no, "parts": parts_total,
        "seconds": round(seconds, 1), "engine": " ".join(cmd) if cmd else None, "engine_version": eng.version(root),
        "fake_engine": bool((ctx.get("qa") or {}).get("fake")), "attempts": gate.get("attempts", []),
        "video": ((gate.get("render") or {}).get("video")) if gate.get("render") else None,
        "contact": ((gate.get("render") or {}).get("contact")) if gate.get("render") else None,
        "sites": site_report, "dropped": dropped, "recommended_title": recommended,
        "script_warnings": [i for i in script_issues if i["level"] == "WARN"],
        "plan_warnings": [i for i in plan_issues if i["level"] == "WARN"],
        "meta_issues": meta_issues, "announce_issues": post_issues, "srt": srt_note,
        "covers": [c["file"] for c in covers], "cover_shot": bool(hero), "image_generator": image_gen["available"],
        "video_url": video_url or None,
        "checklist": rows, "reminder": reminder,
    }
    if write_log and summary["status"] == "ready" and not fake:
        summary["log"] = journal.add(name, recommended, eff["platforms"], seconds, today, root)
    write_text(os.path.join(out_dir, "report.md"), report_markdown(summary))
    write_json(os.path.join(out_dir, "summary.json"), summary)
    return summary


def html_titles(info: Any, lang: str, tags: List[str]) -> List[Dict[str, Any]]:
    """Названия для ролика про HTML-файл. Цифры только те, что код узнал из файла."""
    title = info.title
    kb = info.size_kb
    if lang == "ru":
        rows = [
            (1, "интрига", "ОДИН HTML-ФАЙЛ ВМЕСТО ВИДЕО 😱"),
            (2, "интрига", "%s В ОДНОМ ФАЙЛЕ НА %d КБ 🔥" % (title.upper()[:40], kb)),
            (3, "интрига", "Это не видео, а один HTML-файл"),
            (3, "поиск", "%s: анимация в одном HTML-файле" % title[:50]),
            (4, "поиск", "HTML и JavaScript: целая сцена в %d КБ" % kb),
            (5, "поиск", "Анимация на HTML без движка видео: %s" % title[:40]),
        ]
    else:
        rows = [
            (1, "интрига", "ONE HTML FILE INSTEAD OF A VIDEO 😱"),
            (2, "интрига", "A WHOLE SCENE IN %d KB OF HTML 🔥" % kb),
            (3, "интрига", "This is not a video, it is one HTML file"),
            (3, "поиск", "One HTML file animation, made with code"),
            (4, "поиск", "HTML and JavaScript: a full scene in %d KB" % kb),
            (5, "поиск", "HTML animation without video software"),
        ]
    why = ["капс и эмодзи: шаблон автора для ленты Shorts", "название файла и вес: конкретика вместо обещаний",
           "парадокс без капса: держит любопытство", "что это и как сделано: для поиска",
           "технологии и размер в начале: для поиска по теме", "спокойная поисковая фраза без эмодзи"]
    out = []
    for index, (loud, kind, text) in enumerate(rows):
        out.append({"text": meta._fit(text, tags), "loudness": loud, "for": kind,
                    "why": why[index], "recommended": index == 0})
    return out


def report_markdown(summary: Dict[str, Any]) -> str:
    fake_note = " Рендер проверен только заглушкой движка: видеофайла нет." if summary.get("fake_engine") else ""
    status = {"ready": "ГОТОВО: ролик собран и прошёл QA движка",
              "rendered-qa-failed": "РОЛИК СОБРАН, НО QA НЕ ПРОЙДЕН: правки ниже",
              "plan-ready": "ПЛАН ГОТОВ, ВИДЕО НЕТ: движок SHORTS не вшит." + fake_note,
              "needs-fix": "НУЖНА ПРАВКА: упаковка или анонс не прошли линтер, причины ниже"}[summary["status"]]
    rows = ["# Отчёт по ролику %s" % summary["name"], "", status, ""]
    if summary.get("fake_engine"):
        rows += ["Заглушка (tests/fake_engine.py) проверила только, что план принимается и длина в цели. "
                 "QR, субтитры по словам, safe zone, громкость и первый кадр не проверял никто. "
                 "В журнал ролик не записан.", ""]
    if not summary.get("video_url"):
        rows += ["В анонсе вместо ссылки метка PASTE_VIDEO_URL: после загрузки запусти "
                 "`python3 tools/reel.py announce <папка> --video-url <ссылка на ролик>`.", ""]
    rows.append("Язык: %s. Часть %d из %d. Длина: %.1f с. Движок: %s." % (
        summary["lang"], summary["part"], summary["parts"], summary["seconds"], summary["engine_version"]))
    if summary.get("video"):
        rows.append("Видео: %s" % summary["video"])
    if summary.get("contact"):
        rows.append("Контактный лист: %s" % summary["contact"])
    if summary.get("sites"):
        rows += ["", "## Сайты", ""] + summary["sites"]
    if summary.get("attempts"):
        rows += ["", "## Рендер и QA", ""]
        for a in summary["attempts"]:
            rows.append("- попытка %s: %s" % (a.get("attempt"), json.dumps(a, ensure_ascii=False)))
    rows += ["", "## Чек-лист перед выдачей (20 пунктов)", "", "| # | Пункт | Кто проверил | Итог |", "|---|---|---|---|"]
    for row in summary["checklist"]:
        rows.append("| %s | %s | %s | %s |" % (row["n"], row["what"], row["who"], row["state"]))
    if summary.get("recommended_title"):
        rows += ["", "Рекомендую название: %s" % summary["recommended_title"]]
    rows += ["", "Субтитры .srt: %s." % summary["srt"]]
    rows.append("Обложки: %s%s." % (", ".join(summary["covers"]) if summary["covers"] else "только промпт в cover-prompt.txt",
                                    " (герой: скриншот сайта, shots/shots.txt)" if summary.get("cover_shot") else ""))
    if summary.get("image_generator"):
        rows.append("Генератор картинок найден: фон для обложки можно сгенерировать по cover-prompt.txt.")
    for key, title in (("script_warnings", "Сценарий"), ("plan_warnings", "План"), ("meta_issues", "Упаковка"),
                       ("announce_issues", "Анонс")):
        if summary.get(key):
            rows += ["", "## %s: замечания" % title, ""] + ["- %s %s: %s" % (i["level"], i["code"], i["message"]) for i in summary[key]]
    if summary.get("reminder"):
        rows += ["", summary["reminder"]]
    return fix_dashes("\n".join(rows) + "\n")


def refresh_announce(folder: str, video_url: str, root: Optional[str] = None) -> Dict[str, Any]:
    """После загрузки: вставить ссылку на ролик в анонс и прогнать линтер постов ещё раз."""
    path = os.path.join(folder, "announce.txt")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if VIDEO_PLACEHOLDER not in text:
        return {"changed": False, "issues": announce.lint(text, root), "note": "метки PASTE_VIDEO_URL в анонсе нет"}
    if not re.match(r"^https?://", video_url):
        raise ValueError("ссылка на ролик начинается с http")
    text = text.replace(VIDEO_PLACEHOLDER, video_url)
    write_text(path, text)
    summary_path = os.path.join(folder, "summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, encoding="utf-8") as handle:
            summary = json.load(handle)
        summary["video_url"] = video_url
        write_json(summary_path, summary)
    return {"changed": True, "issues": announce.lint(text, root)}
