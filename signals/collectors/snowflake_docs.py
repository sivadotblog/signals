"""Snowflake "All release notes" page collector.

The page (docs.snowflake.com/en/release-notes/all-release-notes) has no RSS feed and
its .md copy is empty. It is a Next.js page, so the server-rendered HTML carries the
entries as JSON in <script id="__NEXT_DATA__">, under props.pageProps.releases.

Each release has: changeType, date (list: one day, or start and end for a server
release, or ["Upcoming"]), keywords, title ("Oct 19, 2026: Schema variables (General
availability)"), source (docs path), summary, content (HTML), and isBundle for server
releases.

Mapping:
  - Feature updates and other single entries become one Update. The leading date in
    the title is dropped. keywords and changeType become tags.
  - Server releases (isBundle) list each feature as an anchor link under a section
    heading. Each link becomes its own Update with the release title as parent_title
    and the section heading as a tag. The "Release notes change log" section is skipped.
  - Entries whose body is a bold-title bullet list can be split like RSS digests
    (see common.DigestSplitter), off by default.
  - summary is the text of the HTML body, not the page's MDX summary field.
  - Entries dated "Upcoming" are skipped. They come back with a date once released.

Params (from technologies.yaml):
  url           page URL, with filter query params
  base          docs root for relative links, default https://docs.snowflake.com/en/
  split_digest, no_split_title, no_split_bullet, split_min_words   see DigestSplitter
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from ..model import Update
from . import register
from html import unescape

from .common import HREF_RE, DigestSplitter, fetch, slug, text_of

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
TITLE_DATE_RE = re.compile(r"^[A-Z][a-z]{2,8}\.? \d{1,2}, \d{4}\s*:\s*")
SECTION_RE = re.compile(r'<a href="([^"]+)"[^>]*class="[^"]*font-semibold[^"]*"[^>]*>(.*?)</a>\s*(?:<ul[^>]*>(.*?)</ul>)?', re.S)
ANCHOR_RE = re.compile(r'<li>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SKIP_SECTIONS = re.compile(r"\bchange log\b", re.I)


def releases_from_html(html: str) -> list[dict]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__ JSON on the page; the page layout changed")
    data = json.loads(m.group(1))
    return data["props"]["pageProps"]["releases"]


BOILERPLATE_RE = re.compile(r'<p class="(?:ellipsis-text|read-more)">.*?</p>', re.S)


def summary_of(content: str) -> str:
    """Plain text of the entry body. The page's `summary` field is raw MDX (import
    lines, markdown links, escaped underscores), so the HTML body is used instead."""
    return text_of(BOILERPLATE_RE.sub(" ", content or ""))


@register("snowflake-release-notes")
class SnowflakeReleaseNotes:
    def __init__(self, technology: str, id: str, url: str, base: str = "https://docs.snowflake.com/en/",
                 split_digest: bool = False, no_split_title: str | None = None,
                 no_split_bullet: str | None = None, split_min_words: int = 2):
        self.technology = technology
        self.id = id
        self.url = url
        self.base = base
        self.splitter = DigestSplitter(split_digest, no_split_title, no_split_bullet, split_min_words)

    def collect(self, input_path: str | None = None) -> list[Update]:
        html = Path(input_path).read_text(encoding="utf-8") if input_path else fetch(self.url)
        return self.parse(html)

    def abs(self, href: str) -> str:
        """Docs links on the page are root-relative without the locale; resolve them under base."""
        href = unescape(href)
        if href.startswith("/"):
            return urljoin(self.base, href.lstrip("/"))
        return urljoin(self.base, href)

    def links(self, html: str) -> list[str]:
        out = []
        for href in HREF_RE.findall(html or ""):
            u = self.abs(href)
            if u.startswith("http") and u not in out:
                out.append(u)
        return out

    def parse(self, html: str) -> list[Update]:
        out: list[Update] = []
        seen: set[str] = set()
        for r in releases_from_html(html):
            dates = [d for d in r.get("date", []) if ISO_RE.match(d)]
            if not dates:
                continue  # "Upcoming"
            date = dates[0]
            source = r["source"]
            url = self.abs(source)
            change_type = r.get("changeType", "")
            tags = sorted({t for t in r.get("keywords", []) if t} | ({change_type} if change_type else set()))
            title = TITLE_DATE_RE.sub("", " ".join(r.get("title", "").split()))
            content = r.get("content", "")

            items: list[Update] = []
            if r.get("isBundle"):
                for sec_href, sec_title, ul in SECTION_RE.findall(content):
                    section = text_of(sec_title)
                    if SKIP_SECTIONS.search(section):
                        continue
                    for href, text in ANCHOR_RE.findall(ul or ""):
                        link = self.abs(href)
                        items.append(Update(
                            technology=self.technology, source=self.id,
                            source_id=f"{source}{href[href.find('#'):] if '#' in href else '::' + slug(text_of(text))}",
                            date=date, title=text_of(text), url=link, links=[link],
                            tags=sorted(set(tags) | {section}), parent_title=title,
                        ))
            else:
                parts = self.splitter.parts(title, content)
                for sub_title, body, li in parts:
                    items.append(Update(
                        technology=self.technology, source=self.id, source_id=f"{source}::{slug(sub_title)}",
                        date=date, title=sub_title, url=url, summary=text_of(body),
                        links=self.links(li), tags=tags, parent_title=title,
                    ))
                if not parts:
                    summary = summary_of(content)
                    items.append(Update(
                        technology=self.technology, source=self.id, source_id=source, date=date,
                        title=title, url=url, summary=summary,
                        links=[link for link in self.links(content) if link != url], tags=tags,
                    ))
            for u in items:
                if u.source_id not in seen:  # the page can list one release under several filters
                    seen.add(u.source_id)
                    out.append(u)
        return out
