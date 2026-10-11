"""Titles, description, pinned comment, TikTok caption (COMMON.md 8, research 2.3).

The model writes the words (taste), this module keeps the rules:
  DIR/metadata.draft.json (written by the agent, optional):
    {"titles": [{"text": "...", "loudness": 1, "for": "intrigue", "why": "..."}, ...],   5-7, loud -> conservative
     "summary": "1-2 sentences, key words first", "cta": "Полное видео - на канале.",
     "hashtags": {"title": [...], "top": [...], "bottom": [...], "tiktok": [...]},
     "pinned": ["line 1", "line 2", "line 3"], "recommended": 2, "cover_text": "3-5 WORDS"}
  If there is no draft, a rule-based draft is made from the plan (works, but the model should improve it).
Links come only from the plan/prefs (never invented). Output: DIR/metadata.json + DIR/metadata.md.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from .. import memory as M
from ..util import HASHTAG, count_emoji, fix_dashes, has_long_dash, read_json, write_json

MAX_TITLE = 100
DEFAULT_TAGS = {
    "ru": {"title": ["#shorts", "#нейросети", "#ии"], "bottom": ["#shorts", "#ии", "#ai", "#полезное"]},
    "en": {"title": ["#shorts", "#ai", "#tech"], "bottom": ["#shorts", "#ai", "#tools", "#productivity"]},
}
CTA = {"ru": "Полное видео - на канале.", "en": "Full video on the channel."}
EMOJI_LOUD = "\U0001F631"  # the author's pattern uses one emoji in the loud variant


def _tag(t: str) -> str:
    t = t.strip()
    if not t:
        return ""
    t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"), flags=re.U).lower()
    return t if len(t) > 1 else ""


def _uniq(tags: list[str]) -> list[str]:
    out, seen = [], set()
    for t in tags:
        t = _tag(t)
        if t and t not in seen:
            out.append(t)
            seen.add(t)
    return out


def _caps_ratio(text: str) -> float:
    letters = [c for c in HASHTAG.sub("", text) if c.isalpha()]
    return sum(c.isupper() for c in letters) / max(1, len(letters))


def _topic(plan: dict, manifest: dict) -> tuple[str, str]:
    md = plan.get("metadata") or {}
    topic = md.get("topic") or ""
    hook = ""
    for s in plan["scenes"]:
        if s.get("on_screen_text"):
            hook = s["on_screen_text"]
            break
    if not topic:
        topic = hook or (plan["scenes"][0].get("say", "").split(".")[0])
    return fix_dashes(topic.strip()), fix_dashes(hook.strip())


def written(text: str, subs: dict[str, str]) -> str:
    """Spoken form -> written form using captions.subs (e.g. 'эйч ти эм эл' -> 'HTML')."""
    for spoken, wr in sorted(subs.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"(?<!\w)" + re.escape(spoken) + r"(?!\w)", wr, text, flags=re.I | re.U)
    return re.sub(r"\s{2,}", " ", text).strip()


def auto_draft(plan: dict, manifest: dict, lang: str) -> dict:
    """Rule-based fallback. Honest: only words that are in the plan."""
    topic, hook = _topic(plan, manifest)
    subs = (plan.get("captions") or {}).get("subs") or {}
    first_say = written(fix_dashes(plan["scenes"][0].get("say", "")), subs)
    tags = _uniq((plan.get("metadata") or {}).get("hashtags") or DEFAULT_TAGS.get(lang, DEFAULT_TAGS["en"])["title"])
    base = hook or topic
    t = topic.rstrip(".!?")
    if _caps_ratio(t) > 0.6:  # calm variants never shout: sentence case
        t = t[:1].upper() + t[1:].lower()
    if lang == "ru":
        titles = [
            {"text": f"{base.upper()} {EMOJI_LOUD}", "loudness": 1, "for": "intrigue", "why": "капс, эмодзи, крупное обещание"},
            {"text": f"{base.upper()}", "loudness": 2, "for": "intrigue", "why": "капс без эмодзи, для ленты"},
            {"text": f"{t[:1].upper() + t[1:]}: смотри, как это работает", "loudness": 3, "for": "intrigue", "why": "любопытство, без капса"},
            {"text": f"{t[:1].upper() + t[1:]}", "loudness": 4, "for": "search", "why": "суть в начале"},
            {"text": f"{t[:1].upper() + t[1:]} - коротко и по делу", "loudness": 5, "for": "search", "why": "поисковая фраза, спокойно"},
        ]
    else:
        titles = [
            {"text": f"{base.upper()} {EMOJI_LOUD}", "loudness": 1, "for": "intrigue", "why": "caps, one emoji, big promise"},
            {"text": f"{base.upper()}", "loudness": 2, "for": "intrigue", "why": "caps without emoji, for the feed"},
            {"text": f"{t[:1].upper() + t[1:]}: watch how it works", "loudness": 3, "for": "intrigue", "why": "curiosity, no caps"},
            {"text": f"{t[:1].upper() + t[1:]}", "loudness": 4, "for": "search", "why": "key words first"},
            {"text": f"{t[:1].upper() + t[1:]} - quick guide", "loudness": 5, "for": "search", "why": "search phrase, calm"},
        ]
    # one more middle variant from the first spoken line (often the strongest hook)
    if first_say:
        sentence = re.split(r"(?<=[.!?])\s", first_say)[0].rstrip(".")
        titles.insert(2, {"text": sentence, "loudness": 3, "for": "intrigue", "why": "first line of the video" if lang != "ru" else "первая фраза ролика"})
    for x in titles:
        x["hashtags"] = tags[:6]
    summary = first_say or topic
    return {"titles": titles, "summary": summary, "cta": CTA.get(lang, CTA["en"]),
            "hashtags": {"title": tags, "top": tags[1:4] or tags[:3],
                         "bottom": _uniq(DEFAULT_TAGS.get(lang, DEFAULT_TAGS["en"])["bottom"])},
            "recommended": 1, "cover_text": (hook or topic).upper()[:40], "auto": True}


def _links(plan: dict, prefs: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pl = prefs.get("links") or {}
    if isinstance(pl, dict):
        out += [(k, v) for k, v in pl.items() if isinstance(v, str) and v]
    elif isinstance(pl, list):
        out += [("", v) for v in pl if isinstance(v, str)]
    for v in ((plan.get("layout") or {}).get("bottom") or {}).get("links", []):
        if v not in [x[1] for x in out]:
            out.append(("", v))
    for c in (plan.get("layout") or {}).get("cta_in_center", []):
        if c.get("url") and c["url"] not in [x[1] for x in out]:
            out.append(("", c["url"]))
    return out


def _label(name: str, url: str) -> str:
    if name:
        return name[:1].upper() + name[1:]
    host = urllib.parse.urlsplit(url).netloc.lower()
    if "t.me" in host or "telegram" in host:
        return "Telegram"
    if "youtube" in host or "youtu.be" in host:
        return "YouTube"
    if "tiktok" in host:
        return "TikTok"
    if "instagram" in host:
        return "Instagram"
    return host.replace("www.", "") or "Link"


def _utm(url: str, name: str, source: str) -> str:
    if "t.me/" in url or not url.startswith("http"):
        return url
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(u.query) + [("utm_source", source), ("utm_medium", "short"), ("utm_campaign", name)]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), u.fragment))


def build(plan: dict, manifest: dict, draft: dict, prefs: dict) -> dict:
    lang = manifest.get("language", "ru")
    errors: list[str] = []
    warnings: list[str] = []
    tags_d = draft.get("hashtags") or {}
    title_tags = _uniq(tags_d.get("title") or [])
    titles = []
    for i, t in enumerate(draft.get("titles") or []):
        text = fix_dashes(t["text"]).strip()
        own = _uniq(HASHTAG.findall(text))
        text = HASHTAG.sub("", text).strip()
        tags = own or _uniq(t.get("hashtags") or title_tags)
        if "youtube_shorts" in manifest.get("platforms", []) and "#shorts" not in tags:
            tags = ["#shorts"] + tags
        tags = tags[:6]
        full = (text + " " + " ".join(tags)).strip()
        while len(full) > MAX_TITLE and len(tags) > 3:
            tags = tags[:-1]
            full = (text + " " + " ".join(tags)).strip()
        loud = int(t.get("loudness", min(5, i + 1)))
        item = {"n": i + 1, "title": full, "text": text, "hashtags": tags, "loudness": loud, "for": t.get("for", ""),
                "why": t.get("why", ""), "chars": len(full)}
        if len(full) > MAX_TITLE:
            errors.append(f"title {i + 1} is {len(full)} chars > {MAX_TITLE}")
        if count_emoji(full) > 1:
            errors.append(f"title {i + 1} has more than one emoji")
        if loud >= 3 and _caps_ratio(text) > 0.6:
            errors.append(f"title {i + 1}: caps only in the loudest variants (loudness 1-2)")
        if loud >= 4 and count_emoji(text):
            errors.append(f"title {i + 1}: conservative variant with emoji")
        if not 3 <= len(tags) <= 6:
            warnings.append(f"title {i + 1}: {len(tags)} hashtags (pattern: 3-6)")
        titles.append(item)
    titles.sort(key=lambda x: x["loudness"])
    for k, x in enumerate(titles, 1):
        x["n"] = k
    if not 5 <= len(titles) <= 7:
        errors.append(f"{len(titles)} titles, need 5-7")
    rec = int(draft.get("recommended", 1))
    rec = min(max(rec, 0), len(titles) - 1) if titles else 0

    name = manifest.get("name", "short")
    utm = bool((plan.get("metadata") or {}).get("utm"))
    platform = (manifest.get("platforms") or ["youtube_shorts"])[0]
    links = [(_label(n, u), _utm(u, name, platform) if utm else u) for n, u in _links(plan, prefs)]
    if not links:
        warnings.append("no links in prefs or plan: description and pinned comment go without links")
    top = _uniq(tags_d.get("top") or title_tags[1:4])[:3]
    bottom = [t for t in _uniq(tags_d.get("bottom") or []) if t not in top][:6]
    summary = fix_dashes(draft.get("summary", "")).strip()
    cta = fix_dashes(draft.get("cta") or CTA.get(lang, CTA["en"])).strip()
    desc_lines = [" ".join(top), summary, "", cta]
    desc_lines += [f"{lbl}: {u}" for lbl, u in links]
    desc_lines += ["", " ".join(bottom)]
    description = "\n".join(desc_lines).strip() + "\n"
    all_tags = _uniq(HASHTAG.findall(description) + [h for x in titles for h in x["hashtags"]])
    if len(all_tags) > 15:
        warnings.append(f"{len(all_tags)} unique hashtags (keep about 15 or fewer)")
    if len(all_tags) > 60:
        errors.append("more than 60 hashtags: YouTube ignores all of them")
    if len(top) > 3:
        errors.append("more than 3 hashtags above the description")
    if not summary:
        errors.append("description has no text")

    pinned = draft.get("pinned")
    if not pinned:
        link = links[0][1] if links else ""
        if lang == "ru":
            pinned = [summary.split(".")[0][:90] + ".", f"Ссылка: {link}" if link else "Ссылка в профиле.",
                      "Что показать следующим? Пиши в комментах."]
        else:
            pinned = [summary.split(".")[0][:90] + ".", f"Link: {link}" if link else "Link in profile.",
                      "Which one should I show next? Tell me in the comments."]
    pinned = [fix_dashes(x) for x in pinned][:3]
    tk_tags = _uniq(tags_d.get("tiktok") or [t for t in (title_tags + bottom) if t != "#shorts"])[:5]
    tiktok = f"{fix_dashes(titles[rec]['text']) if titles else summary} {' '.join(tk_tags)}".strip()
    if len(tk_tags) > 5:
        errors.append("TikTok: more than 5 hashtags")
    for fld, txt in (("description", description), ("pinned", "\n".join(pinned)), ("tiktok", tiktok)):
        if has_long_dash(txt):
            errors.append(f"long dash in {fld}")
    srt = ""
    return {
        "titles": titles, "recommended": rec + 1 if titles else None,
        "recommended_title": titles[rec]["title"] if titles else "",
        "recommended_why": titles[rec]["why"] if titles else "",
        "description": description, "pinned_comment": pinned, "tiktok_caption": tiktok,
        "hashtags_unique": len(all_tags), "links": links, "cover_text": draft.get("cover_text", ""),
        "auto_draft": bool(draft.get("auto")), "errors": errors, "warnings": warnings, "srt": srt,
        "ai_label_reminder": True,
    }


def to_md(meta: dict, lang: str, manifest: dict) -> str:
    ru = lang == "ru"
    out = ["# " + ("Подписи" if ru else "Packaging") + f": {manifest.get('name')}", ""]
    out.append("## " + ("Названия (от громкого к спокойному)" if ru else "Titles (loud to conservative)"))
    out.append("")
    for t in meta["titles"]:
        mark = " **<- рекомендую**" if ru and t["n"] == meta["recommended"] else (" **<- recommended**" if t["n"] == meta["recommended"] else "")
        out.append(f"{t['n']}. `{t['title']}`  ({'громкость' if ru else 'loudness'} {t['loudness']}, {t['for']}, {t['chars']} {'зн.' if ru else 'chars'}){mark}")
        if t["why"]:
            out.append(f"   - {t['why']}")
    out += ["", ("Почему рекомендую: " if ru else "Why: ") + (meta["recommended_why"] or "-"), ""]
    out += ["## " + ("Описание" if ru else "Description"), "", "```", meta["description"].rstrip(), "```", ""]
    out += ["## " + ("Закреплённый комментарий" if ru else "Pinned comment"), "", "```", *meta["pinned_comment"], "```", ""]
    out += ["## TikTok", "", "```", meta["tiktok_caption"], "```", ""]
    out += ["## " + ("Файлы" if ru else "Files"), "", "- captions.srt " + ("(загрузить в YouTube как субтитры)" if ru else "(upload to YouTube as subtitles)")]
    if meta["auto_draft"]:
        out += ["", ("> Черновик собран правилами. Модель должна переписать названия в metadata.draft.json и перезапустить meta."
                     if ru else "> Rule-based draft. The model should rewrite titles in metadata.draft.json and re-run meta.")]
    out += ["", ("Перед загрузкой: проверь пометку «изменённый или синтетический контент» (реалистичный ИИ-контент)."
                 if ru else "Before upload: check the 'altered or synthetic content' label (realistic AI content).")]
    for e in meta["errors"]:
        out.append(f"- ERROR: {e}")
    for w in meta["warnings"]:
        out.append(f"- warn: {w}")
    return "\n".join(out) + "\n"


def package_dir(d: Path, topic: str | None = None, hashtags: list[str] | None = None, cta: str | None = None) -> dict:
    manifest = read_json(d / "manifest.json")
    plan = read_json(d / "plan.resolved.json")
    if topic:
        plan.setdefault("metadata", {})["topic"] = topic
    if hashtags:
        plan.setdefault("metadata", {})["hashtags"] = hashtags
    lang = manifest.get("language", "ru")
    draft_p = d / "metadata.draft.json"
    draft = read_json(draft_p) if draft_p.exists() else auto_draft(plan, manifest, lang)
    if cta:
        draft["cta"] = cta
    if not draft_p.exists():
        write_json(draft_p, draft)
    meta = build(plan, manifest, draft, M.load())
    write_json(d / "metadata.json", meta)
    (d / "metadata.md").write_text(to_md(meta, lang, manifest), encoding="utf-8")
    meta["ok"] = not meta["errors"]
    return meta
