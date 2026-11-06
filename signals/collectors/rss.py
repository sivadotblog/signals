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
                 no_split_bullet: str | None = None, split_min_words: int = 2):
        self.technology = technology
        self.id = id
        self.url = url
        self.link_base = link_base
        self.include = re.compile(title_include, re.I) if title_include else None
        self.exclude = re.compile(title_exclude, re.I) if title_exclude else None
        self.splitter = DigestSplitter(split_digest, no_split_title, no_split_bullet, split_min_words)

    def collect(self, input_path: str | None = None) -> list[Update]:
        xml = Path(input_path).read_text(encoding="utf-8") if input_path else fetch(self.url)
        return self.parse(xml)

    def parse(self, xml: str) -> list[Update]:
        root = ET.fromstring(xml)
        out: list[Update] = []
        for item in root.iter("item"):
            title = " ".join((item.findtext("title") or "").split())
            if not title:
                continue
            if self.include and not self.include.search(title):
                continue
            if self.exclude and self.exclude.search(title):
                continue
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link or title).strip()
            date = iso_date(item.findtext("pubDate") or "")
            desc = item.findtext("description") or ""
            # Some feeds escape the HTML twice.
            if "&lt;" in desc and "<" not in desc:
                desc = unescape(desc)
            base = self.link_base or link or self.url
            tags = sorted({" ".join((c.text or "").split()) for c in item.findall("category") if c.text})
            url = link or guid

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
