"""Разбор сырья автора: пост, список ссылок, HTML-файл, видео или просто текст.

Посты канала хранятся без ссылок (Телеграм прячет их в словах), поэтому у пункта
может не быть адреса. Тогда адрес берём из реестра сайтов (sites.json) или из
ссылок, которые автор дал рядом. Нет нигде: пункт честно помечается «нет ссылки».
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .common import URL_RE, mod_root, read_json, short_link

RUBRICS = ("абуз", "сервисы", "гайд", "релиз", "девлог", "личное", "опрос",
           "шортс", "лидмагнит", "неробит", "реклама")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
HTML_EXT = (".html", ".htm")
YOUTUBE_RE = re.compile(r"^(https?://)?(www\.|m\.)?(youtube\.com/|youtu\.be/)", re.I)
LINK_MD = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
LINK_BARE = re.compile(r"\[([^\]]+)\](?!\()")
NUM_HEAD = re.compile(r"^\s*(\d{1,2})[.)]\s+")
FOOTER_WORDS = ("ЧАТ", "GITHUB", "YOUTUBE", "ТГК")


@dataclass
class Item:
    name: str
    lead: str = ""
    url: Optional[str] = None
    url_from: Optional[str] = None
    extra: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Raw:
    kind: str
    text: str = ""
    path: Optional[str] = None
    hook: str = ""
    rubric: Optional[str] = None
    items: List[Item] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["items"] = [item.to_dict() for item in self.items]
        return data


def registry(root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    data = read_json(os.path.join(mod_root(root), "sites.json"), {}) or {}
    return data.get("sites", {})


def norm_name(text: str) -> str:
    low = (text or "").lower().replace("ё", "е")
    return re.sub(r"[^a-z0-9а-я]+", "", low)


def lookup(name: str, url: Optional[str] = None, root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Запись реестра по имени пункта или по домену ссылки."""
    key = norm_name(name)
    host = short_link(url or "").split("/")[0].lower() if url else ""
    for site_id, row in registry(root).items():
        names = [site_id] + list(row.get("aliases", []))
        if key and any(norm_name(alias) == key for alias in names):
            return dict(row, id=site_id)
        if host and short_link(row.get("url", "")).split("/")[0].lower() == host:
            return dict(row, id=site_id)
    return None


def _clean_head(line: str) -> str:
    head = NUM_HEAD.sub("", line).strip()
    head = LINK_MD.sub(lambda m: m.group(1), head)
    head = LINK_BARE.sub(lambda m: m.group(1), head)
    return head.strip().rstrip(".:").strip()


def _head_url(line: str) -> Optional[str]:
    match = LINK_MD.search(line)
    if match and match.group(2).startswith("http"):
        return match.group(2)
    match = URL_RE.search(line)
    return match.group(0) if match else None


def _is_footer(line: str) -> bool:
    up = line.upper()
    return sum(1 for word in FOOTER_WORDS if word in up) >= 3 or line.strip() == "[ФУТЕР]"


def _is_hashtag_line(line: str) -> bool:
    parts = line.split()
    return bool(parts) and all(part.startswith("#") for part in parts)


def _looks_like_head(line: str) -> bool:
    """Шапка пункта: короткое название с точкой, часто ссылкой или номером."""
    text = line.strip()
    if not text or text.startswith(("-", "#", "<!--")):
        return False
    bare = _clean_head(text)
    if not bare or len(bare) > 70 or len(bare.split()) > 8:
        return False
    return text.endswith((".", ":")) or bool(LINK_MD.search(text) or LINK_BARE.search(text))


def parse_post(text: str, links: Optional[Dict[str, str]] = None,
               root: Optional[str] = None) -> Raw:
    """Пост канала -> крючок, рубрика и пункты (название, подводка, ссылка)."""
    links = {norm_name(k): v for k, v in (links or {}).items()}
    lines = [line.rstrip() for line in (text or "").splitlines()]
    raw = Raw(kind="post", text=text)
    items: List[Item] = []
    pre: List[str] = []
    current: Optional[Item] = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if _is_footer(stripped):
            current = None
            continue
        if _is_hashtag_line(stripped):
            for tag in stripped.split():
                tag = tag.lstrip("#").lower()
                if tag in RUBRICS:
                    raw.rubric = tag
            current = None
            continue
        nxt = ""
        for after in lines[index + 1:]:
            if after.strip():
                nxt = after.strip()
                break
        numbered = bool(NUM_HEAD.match(stripped))
        inline = None
        if numbered:
            body = NUM_HEAD.sub("", stripped)
            match = re.match(r"^(\[[^\]]+\](?:\([^)]+\))?)\.?\s*(.*)$", body)
            if match:
                inline = (match.group(1), match.group(2).strip())
            elif "." in body:
                head, _, rest = body.partition(". ")
                inline = (head, rest.strip())
        if numbered and inline:
            head_md, rest = inline
            current = Item(name=_clean_head(head_md), lead=rest, url=_head_url(head_md),
                           url_from="post" if _head_url(head_md) else None)
            items.append(current)
            continue
        if _looks_like_head(stripped) and nxt.startswith("-") and (items or pre):
            current = Item(name=_clean_head(stripped), url=_head_url(stripped),
                           url_from="post" if _head_url(stripped) else None)
            items.append(current)
            continue
        if current is not None:
            body = stripped.lstrip("-").strip()
            if not current.lead:
                current.lead = body
            else:
                current.extra.append(body)
            continue
        pre.append(stripped)

    # Крючок: последняя строка до первого пункта. Если строк две и первая без цифр,
    # первая это приветствие, а не крючок.
    if pre:
        raw.hook = pre[-1] if len(pre) == 1 or not re.search(r"\d", pre[0]) else pre[0]
    for item in items:
        _resolve(item, links, root)
    raw.items = items
    if not items:
        raw.notes.append("в посте не нашёл пунктов: ролик пойдёт по тексту")
    return raw


def _resolve(item: Item, links: Dict[str, str], root: Optional[str]) -> None:
    key = norm_name(item.name)
    if not item.url and key in links:
        item.url, item.url_from = links[key], "author"
    if not item.url:
        row = lookup(item.name, root=root)
        if row and row.get("url"):
            item.url = row["url"]
            item.url_from = "search" if row.get("found_by_search") else "registry"


def parse_links(text: str, root: Optional[str] = None) -> Raw:
    """Список ссылок, по одной на строку, с подписью или без."""
    raw = Raw(kind="links", text=text)
    for line in (text or "").splitlines():
        match = URL_RE.search(line)
        if not match:
            continue
        url = match.group(0).rstrip(".,;")
        rest = (line[:match.start()] + " " + line[match.end():]).strip(" -:|\t")
        row = lookup("", url=url, root=root)
        name = (row or {}).get("title") or short_link(url).split("/")[0]
        raw.items.append(Item(name=name, lead=rest, url=url, url_from="author"))
    return raw


def detect(source: str, links: Optional[Dict[str, str]] = None,
           root: Optional[str] = None) -> Raw:
    """Что принёс автор. source это путь к файлу или сам текст."""
    candidate = source.strip()
    if len(candidate) < 400 and "\n" not in candidate and os.path.isfile(candidate):
        low = candidate.lower()
        if low.endswith(HTML_EXT):
            return Raw(kind="html", path=os.path.abspath(candidate))
        if low.endswith(VIDEO_EXT):
            return Raw(kind="video", path=os.path.abspath(candidate))
        with open(candidate, encoding="utf-8") as handle:
            return detect(handle.read(), links, root)
    if YOUTUBE_RE.match(candidate) and "\n" not in candidate:
        return Raw(kind="video", text=candidate)
    filled = [line for line in candidate.splitlines() if line.strip()]
    url_lines = [line for line in filled if URL_RE.search(line) and not LINK_MD.search(line)]
    if filled and len(url_lines) / len(filled) >= 0.6:
        return parse_links(candidate, root)
    post = parse_post(candidate, links, root)
    if post.items or post.rubric:
        return post
    return Raw(kind="text", text=candidate, hook=filled[0] if filled else "")
