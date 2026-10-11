"""Plan loading, schema validation and rule lint (things a script can check before rendering)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .config import skill_root, schema_path
from .engine import layout as L
from .util import ShortsError, count_emoji, has_long_dash, read_json, script_ratio

GREETINGS = {
    "ru": [r"^\s*привет", r"^\s*всем привет", r"^\s*в этом видео", r"^\s*сегодня я (вам )?расскажу", r"^\s*смотрите", r"^\s*здравствуйте"],
    "en": [r"^\s*hi\b", r"^\s*hello\b", r"^\s*hey (guys|everyone)", r"^\s*in this video", r"^\s*today i('| a)m going to", r"^\s*welcome"],
}
GOODBYES = {
    "ru": [r"\bвсем пока\b", r"\bпока[!.]?\s*$", r"\bдо встречи\b", r"\bдо скорого\b", r"\bувидимся\b"],
    "en": [r"\bbye\b", r"\bsee you\b", r"\bthat'?s all\b", r"\bthanks for watching\b"],
}


@dataclass
class Issue:
    level: str  # error | warn
    code: str
    msg: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.msg}"


def load(path: Path | str) -> tuple[dict, Path]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ShortsError(f"plan not found: {p}")
    return read_json(p), p.parent


def schema() -> dict:
    return read_json(schema_path("plan.schema.json"))


def validate_schema(plan: dict) -> list[Issue]:
    v = jsonschema.Draft202012Validator(schema())
    out = []
    for e in sorted(v.iter_errors(plan), key=lambda e: list(e.path)):
        where = "/".join(str(x) for x in e.path) or "(root)"
        out.append(Issue("error", "schema", f"{where}: {e.message}"))
    return out


def lang2(plan: dict) -> str:
    return (plan.get("meta", {}).get("language") or "ru")[:2].lower()


def resolve_ref(ref: str, plan_dir: Path | None) -> Path | None:
    p = Path(ref).expanduser()
    if p.is_absolute():
        return p if p.exists() else None
    for b in (plan_dir, skill_root()):
        if b and (b / p).exists():
            return (b / p).resolve()
    return None


def lint(plan: dict, plan_dir: Path | None = None) -> list[Issue]:
    """Rules from COMMON.md that can be checked on the plan alone."""
    out: list[Issue] = []
    lang = lang2(plan)
    lay = plan.get("layout", {})
    mode = lay.get("mode", "three")
    try:
        geo = L.compute(lay, plan["meta"].get("platforms", ["youtube_shorts"]))
        if geo.center_pct < L.CENTER_MIN * 100:
            out.append(Issue("error", "center", f"center is {geo.center_pct:.0f}% of height, must be >= 55%"))
    except ShortsError as e:
        out.append(Issue("error", "layout", str(e)))
    for side in ("top", "bottom"):
        pct = (lay.get(side) or {}).get("height_pct")
        if pct is not None and pct > 20:
            out.append(Issue("error", "panel", f"{side} panel {pct}% > 20%"))
    if mode in ("three", "top_center"):
        src = (lay.get("top") or {}).get("source")
        if not src:
            out.append(Issue("error", "empty_top", "top panel has no source: give a video or html, or switch layout to center_bottom/center_only"))
        elif src.startswith("color:"):
            out.append(Issue("warn", "empty_top", "top panel is a solid colour: it is an empty panel and will fail QA"))
        elif not src.startswith("html:") and not resolve_ref(src, plan_dir):
            out.append(Issue("error", "top_source", f"top panel source not found: {src}"))
    if mode in ("three", "center_bottom"):
        b = lay.get("bottom") or {}
        if not (b.get("handle") or b.get("links")):
            out.append(Issue("error", "empty_bottom", "bottom panel has no handle or links: ask the user or switch layout"))
    ctas = lay.get("cta_in_center") or []
    if len(ctas) > 3:
        out.append(Issue("error", "cta", "more than 3 CTA flashes"))
    for c in ctas:
        if c["kind"] == "qr" and not c.get("url"):
            out.append(Issue("error", "cta_qr", "QR flash needs url"))
        if c["kind"] in ("handle", "text") and not (c.get("text") or (lay.get("bottom") or {}).get("handle")):
            out.append(Issue("error", "cta_text", f"{c['kind']} flash needs text"))
    if ctas and not any(c["kind"] == "qr" for c in ctas):
        out.append(Issue("warn", "cta_qr", "no QR flash: the research suggests QR + short link in the last 3-4 s"))

    br = plan.get("brand", {})
    eff = br.get("effects") or {}
    for k in ("text_glow", "gradient_plate"):
        if eff.get(k):
            out.append(Issue("error", "slop", f"brand.effects.{k} is on: glow and gradient plates are banned (QA will fail)"))
    pal = br.get("palette") or {}
    if len({v.upper() for v in pal.values() if v}) > 3:
        out.append(Issue("error", "palette", "more than 3 base colours"))

    cap = plan.get("captions", {})
    if cap.get("enabled", True) and cap.get("max_words", 3) > 3:
        out.append(Issue("warn", "captions", "max_words > 3: the rule is 2-3 words per chunk"))
    if cap.get("size") and cap["size"] < 64:
        out.append(Issue("error", "captions", "caption size < 64 px"))

    scenes = plan.get("scenes", [])
    ids = [s.get("id") for s in scenes]
    if len(set(ids)) != len(ids):
        out.append(Issue("error", "scenes", "scene ids must be unique"))
    all_text = []
    for i, s in enumerate(scenes):
        say, ost = s.get("say", ""), s.get("on_screen_text", "")
        all_text += [say, ost]
        for fld, txt in (("say", say), ("on_screen_text", ost)):
            if has_long_dash(txt):
                out.append(Issue("error", "dash", f"scene {s.get('id')}: long dash in {fld}, use '-'"))
        if count_emoji(ost):
            out.append(Issue("error", "emoji", f"scene {s.get('id')}: emoji in on-screen text"))
        if not s.get("why"):
            out.append(Issue("warn", "why", f"scene {s.get('id')}: no 'why' (design rule 7: no answer, remove the layer)"))
        if not say and not s.get("duration") and s["source"]["type"] not in ("video", "film"):
            out.append(Issue("error", "duration", f"scene {s.get('id')}: no say and no duration"))
        src = s["source"]
        if src["type"] in ("html", "video", "images") and src.get("ref") and not src["ref"].startswith(("http://", "https://")):
            if not resolve_ref(src["ref"], plan_dir):
                out.append(Issue("error", "source", f"scene {s.get('id')}: file not found {src['ref']}"))
        if src["type"] == "site" and not (src.get("ref") or any(a.get("url") for a in src.get("actions", []))):
            out.append(Issue("error", "source", f"scene {s.get('id')}: site scene needs ref or goto url"))
        for sp in s.get("speed", []):
            if not 0.25 <= sp["rate"] <= 4:
                out.append(Issue("warn", "speed", f"scene {s.get('id')}: rate {sp['rate']} outside 0.25-4"))
    if scenes:
        first = scenes[0].get("say", "")
        for pat in GREETINGS.get(lang, []):
            if re.search(pat, first, re.I):
                out.append(Issue("error", "hook", "first line starts with a greeting: start with the result or a question"))
                break
        last = scenes[-1].get("say", "")
        for pat in GOODBYES.get(lang, []):
            if re.search(pat, last, re.I):
                out.append(Issue("error", "loop", "last line says goodbye: it breaks the loop"))
                break
    joined = " ".join(t for t in all_text if t)
    sr = script_ratio(joined)
    if sr["letters"] > 20:
        if lang == "ru" and sr["cyrillic"] < 0.5:
            out.append(Issue("warn", "language", "plan language is ru but most text is Latin"))
        if lang == "en" and sr["cyrillic"] > 0.2:
            out.append(Issue("warn", "language", "plan language is en but text has Cyrillic"))
    return out


def check(plan: dict, plan_dir: Path | None = None) -> list[Issue]:
    issues = validate_schema(plan)
    if not issues:
        issues += lint(plan, plan_dir)
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def with_defaults(plan: dict) -> dict:
    p = copy.deepcopy(plan)
    p["meta"].setdefault("fps", 30)
    p["meta"].setdefault("loop", True)
    p.setdefault("captions", {}).setdefault("enabled", True)
    p["captions"].setdefault("max_words", 3)
    p["captions"].setdefault("highlight", "accent")
    p["captions"].setdefault("subs", {})
    au = p.setdefault("audio", {})
    au.setdefault("voice", {}).setdefault("engine", "auto")
    au.setdefault("target_lufs", -14)
    au.setdefault("sfx_auto", True)
    p["layout"].setdefault("cta_in_center", [])
    p.setdefault("metadata", {})
    p.setdefault("fx", {})
    return p
