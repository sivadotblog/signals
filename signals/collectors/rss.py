"""Generic RSS 2.0 collector.

One feed item becomes one Update, unless `split_digest` is on and the item is a
digest. A digest is an item whose description has list items that start with a
bold title and a colon, e.g.
  <li><strong>Analyze files in volumes (Public Preview)</strong>: A Genie Agent can now ...</li>
Each such list item becomes its own Update, with the feed title kept as parent_title.

Params (from technologies.yaml):
  url            feed URL
  split_digest   split digest items, default false
  link_base      base URL for relative links in descriptions, default: the item link
  title_include  optional regex; keep only items whose title matches
  title_exclude  optional regex; drop items whose title matches
"""

from __future__ import annotations

import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from ..model import Update
from . import register

UA = "signals-collector/0.1 (+https://github.com/sivadotblog/signals)"
LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.I | re.S)
DIGEST_LI_RE = re.compile(r"^\s*<(strong|b)>(.*?)</\1>\s*:?\s*(.*)$", re.I | re.S)
HREF_RE = re.compile(r'href\s*=\s*"([^"]+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def text_of(html: str) -> str:
    text = " ".join(unescape(TAG_RE.sub(" ", html)).split())
    return re.sub(r"\s+([.,;:!?)])", r"\1", text)  # tags leave a space before punctuation


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


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def links_in(html: str, base: str) -> list[str]:
    out = []
    for href in HREF_RE.findall(html):
        u = urljoin(base, unescape(href))
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


@register("rss")
class RssCollector:
    def __init__(self, technology: str, id: str, url: str, split_digest: bool = False,
                 link_base: str | None = None, title_include: str | None = None,
                 title_exclude: str | None = None):
        self.technology = technology
        self.id = id
        self.url = url
        self.split_digest = split_digest
        self.link_base = link_base
        self.include = re.compile(title_include, re.I) if title_include else None
        self.exclude = re.compile(title_exclude, re.I) if title_exclude else None

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

            parts = []
            if self.split_digest:
                for li in LI_RE.findall(desc):
                    m = DIGEST_LI_RE.match(li)
                    if m:
                        parts.append((text_of(m.group(2)), m.group(3), li))
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
