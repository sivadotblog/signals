"""Generic RSS 2.0 collector.

One feed item becomes one Update, unless `split_digest` is on and the item is a
digest. A digest is an item whose description has list items that start with a
bold title and a colon, e.g.
  <li><strong>Analyze files in volumes (Public Preview)</strong>: A Genie Agent can now ...</li>
Each such list item becomes its own Update, with the feed title kept as parent_title.

Params (from technologies.yaml):
  url             feed URL
  split_digest    split digest items, default false
  link_base       base URL for relative links in descriptions, default: the item link
  title_include   optional regex; keep only items whose title matches
  title_exclude   optional regex; drop items whose title matches
  no_split_title, no_split_bullet, split_min_words   see common.DigestSplitter

Atom feeds (<feed><entry>) are read too: title, id, updated, link rel="alternate",
content or summary.

Section split, for feeds where one entry holds several changes under type headings
(e.g. Google Cloud: <h3>Feature</h3><p>...</p><h3>Fixed</h3><p>...</p>):
  split_heading  tag name of the type heading, e.g. h3. Each heading starts one Update.
                 The heading text (Feature, Fixed, Deprecated ...) becomes a tag.
                 Title is the first sentence of the section text.
  label_link     regex on href. The text of the first link that matches becomes the
                 Update's label (e.g. a link to the vendor's launch-stages page with
                 text "Preview" or "GA"). Matching links are left out of `links`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from ..model import Update
from . import register
from .common import DigestSplitter, fetch, links_in, slug, text_of

ATOM = "{http://www.w3.org/2005/Atom}"
ANCHOR_RE = re.compile(r'<a\b[^>]*href\s*=\s*"([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def first_sentence(text: str) -> str:
    return SENTENCE_END.split(text.strip(), maxsplit=1)[0] if text else ""


def iso_date(pub: str) -> str:
    pub = (pub or "").strip()
    if not pub:
        return ""
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", pub)  # ISO 8601 fallback
    return m.group(1) if m else ""


@register("rss")
class RssCollector:
    def __init__(self, technology: str, id: str, url: str, split_digest: bool = False,
                 link_base: str | None = None, title_include: str | None = None,
                 title_exclude: str | None = None, no_split_title: str | None = None,
                 no_split_bullet: str | None = None, split_min_words: int = 2,
                 split_heading: str | None = None, label_link: str | None = None):
        self.technology = technology
        self.id = id
        self.url = url
        self.link_base = link_base
        self.include = re.compile(title_include, re.I) if title_include else None
        self.exclude = re.compile(title_exclude, re.I) if title_exclude else None
        self.splitter = DigestSplitter(split_digest, no_split_title, no_split_bullet, split_min_words)
        self.split_heading = split_heading
        self.label_link = re.compile(label_link, re.I) if label_link else None

    def collect(self, input_path: str | None = None) -> list[Update]:
        xml = Path(input_path).read_text(encoding="utf-8") if input_path else fetch(self.url)
        return self.parse(xml)

    def entries(self, root: ET.Element):
        """(title, link, guid, pubDate, html, categories) per RSS item or Atom entry."""
        if root.tag == f"{ATOM}feed":
            for e in root.iter(f"{ATOM}entry"):
                link = next((ln.get("href", "") for ln in e.findall(f"{ATOM}link")
                             if ln.get("rel", "alternate") == "alternate"), "")
                html = e.findtext(f"{ATOM}content") or e.findtext(f"{ATOM}summary") or ""
                cats = [c.get("term", "") for c in e.findall(f"{ATOM}category")]
                yield (e.findtext(f"{ATOM}title") or "", link, e.findtext(f"{ATOM}id") or "",
                       e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published") or "", html, cats)
        else:
            for item in root.iter("item"):
                yield (item.findtext("title") or "", item.findtext("link") or "", item.findtext("guid") or "",
                       item.findtext("pubDate") or "", item.findtext("description") or "",
                       [c.text or "" for c in item.findall("category")])

    def sections(self, html: str) -> list[tuple[str, str]]:
        """(heading text, section html) per split_heading."""
        tag = re.escape(self.split_heading)
        parts = re.split(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.I | re.S)
        return [(text_of(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]

    def label_and_links(self, html: str, base: str) -> tuple[str, list[str]]:
        label = ""
        if self.label_link:
            for href, text in ANCHOR_RE.findall(html):
                if self.label_link.search(href):
                    label = text_of(text)
                    break
        links = [u for u in links_in(html, base) if not (self.label_link and self.label_link.search(u))]
        return label, links

    def parse(self, xml: str) -> list[Update]:
        root = ET.fromstring(xml)
        out: list[Update] = []
        for raw_title, raw_link, raw_guid, pub, desc, cats in self.entries(root):
            title = " ".join(raw_title.split())
            if not title:
                continue
            if self.include and not self.include.search(title):
                continue
            if self.exclude and self.exclude.search(title):
                continue
            link = raw_link.strip()
            guid = (raw_guid or link or title).strip()
            date = iso_date(pub)
            # Some feeds escape the HTML twice.
            if "&lt;" in desc and "<" not in desc:
                desc = unescape(desc)
            base = self.link_base or link or self.url
            tags = sorted({" ".join(c.split()) for c in cats if c and c.strip()})
            url = link or guid

            if self.split_heading:
                used: set[str] = set()
                for kind_label, sec in self.sections(desc):
                    text = text_of(sec)
                    if not text:
                        continue
                    label, links = self.label_and_links(sec, base)
                    key = slug(first_sentence(text))
                    sid = f"{guid}::{slug(kind_label)}::{key}"
                    n = 2
                    while sid in used:  # same type and same first sentence twice in one entry
                        sid = f"{guid}::{slug(kind_label)}::{key}-{n}"
                        n += 1
                    used.add(sid)
                    out.append(Update(
                        technology=self.technology, source=self.id, source_id=sid, date=date,
                        title=first_sentence(text), url=url, summary=text, links=links,
                        tags=sorted(set(tags) | {kind_label}), parent_title=title, label=label,
                    ))
                continue

            parts = self.splitter.parts(title, desc)
            if parts:
                for sub_title, body, li in parts:
                    out.append(Update(
                        technology=self.technology, source=self.id,
                        source_id=f"{guid}::{slug(sub_title)}", date=date,
                        title=sub_title, url=url, summary=text_of(body),
                        links=links_in(li, base), tags=tags, parent_title=title,
                    ))
            else:
                out.append(Update(
                    technology=self.technology, source=self.id, source_id=guid, date=date,
                    title=title, url=url, summary=text_of(desc),
                    links=links_in(desc, base), tags=tags,
                ))
        return out
