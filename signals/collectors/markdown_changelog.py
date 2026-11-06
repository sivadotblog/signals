"""Markdown changelog collector.

For vendors that publish a changelog page as markdown (often the docs page URL with
.md appended). Layout it expects:

  ## 2026 Releases                      year group, optional, ignored
  ### October 2026                       release heading: date with or without day
  - Public Preview: Adds X. See [Y](/docs/y/#anchor).     one change per bullet
    continuation lines and nested bullets belong to the bullet above

Each top-level bullet under a release heading becomes one Update:
  title      the bullet text with markdown links turned into plain text, and the
             status label removed (it goes to `label`)
  label      the status prefix, when the bullet starts with one (`label_prefix` regex)
  date       from the heading. "10 December 2025 Release" gives 2025-12-10.
             "October 2026" gives 2026-10-01 with date_precision "month".
  url        page URL plus the heading anchor
  links      every link in the bullet, absolute
  source_id  page + heading anchor + first link (path and anchor), or a slug of the
             text when the bullet has no link. Ties within one release get the text slug.

Headings that do not parse as a date are not releases. Their bullets are skipped.

Params (from technologies.yaml):
  url              markdown URL
  page_url         human page URL for links, default: url without the .md suffix
  release_level    heading level of releases, default 3
  label_prefix     regex with one group for the label, default the common status words
  capability_hint  set on every record, for product-specific changelogs
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ..model import Update
from . import register
from .common import fetch, slug

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")
MONTH_DAY_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b")
MONTH_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{4})\b")
ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\b")
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BULLET = re.compile(r"^[-*+]\s+(.*)$")
DEFAULT_LABEL = r"^(General Availability|Public Preview|Private Preview|Preview|Beta|Experimental)\s*:\s*"


def heading_date(text: str) -> tuple[str, str] | None:
    """(YYYY-MM-DD, precision) from a release heading, or None."""
    t = text.strip()
    for rx, order in ((ISO, "ymd"), (DAY_MONTH_YEAR, "dmy"), (MONTH_DAY_YEAR, "mdy")):
        m = rx.match(t)
        if m:
            if order == "ymd":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif order == "dmy":
                d, mo, y = int(m[1]), MONTHS.get(m[2].lower()), int(m[3])
            else:
                mo, d, y = MONTHS.get(m[1].lower()), int(m[2]), int(m[3])
            if mo and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}", "day"
    m = MONTH_YEAR.match(t)
    if m and MONTHS.get(m[1].lower()):
        return f"{int(m[2]):04d}-{MONTHS[m[1].lower()]:02d}-01", "month"
    return None


def plain(md: str) -> str:
    text = MD_LINK.sub(r"\1", md)
    text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)  # emphasis
    text = text.replace("`", "")
    return " ".join(text.split())


@register("markdown-changelog")
class MarkdownChangelog:
    def __init__(self, technology: str, id: str, url: str, page_url: str | None = None,
                 release_level: int = 3, label_prefix: str = DEFAULT_LABEL, capability_hint: str = ""):
        self.technology = technology
        self.id = id
        self.url = url
        self.page_url = page_url or re.sub(r"\.md$", "", url)
        if not self.page_url.endswith("/") and not urlparse(self.page_url).path.rsplit("/", 1)[-1].count("."):
            self.page_url += "/"
        self.release_prefix = "#" * release_level + " "
        self.label_rx = re.compile(label_prefix, re.I)
        self.hint = capability_hint

    def collect(self, input_path: str | None = None) -> list[Update]:
        md = Path(input_path).read_text(encoding="utf-8") if input_path else fetch(self.url)
        if not md.strip():
            raise RuntimeError(f"{self.id}: {self.url} returned an empty page")
        return self.parse(md)

    def bullets(self, md: str):
        """Yield (heading text, bullet markdown) for top-level bullets under release headings."""
        heading = None
        cur: list[str] | None = None
        for line in md.splitlines():
            hm = re.match(r"^(#{1,6})\s+(.*)$", line)
            if hm:
                if cur is not None and heading:
                    yield heading, "\n".join(cur)
                cur = None
                level = len(hm.group(1))
                if level == len(self.release_prefix) - 1:
                    heading = hm.group(2).strip()
                elif level < len(self.release_prefix) - 1:
                    heading = None  # a year group or page title ends the release
                # deeper headings are sub-sections; bullets under them stay in the release
                continue
            if heading is None:
                continue
            m = BULLET.match(line)
            if m:
                if cur is not None:
                    yield heading, "\n".join(cur)
                cur = [m.group(1)]
            elif cur is not None and (line.startswith((" ", "\t")) or not line.strip()):
                cur.append(line.strip())
            elif cur is not None:
                yield heading, "\n".join(cur)  # unindented text ends the bullet
                cur = None
        if cur is not None and heading:
            yield heading, "\n".join(cur)

    def parse(self, md: str) -> list[Update]:
        out: list[Update] = []
        used: set[str] = set()
        for heading, body in self.bullets(md):
            hd = heading_date(heading)
            if not hd:
                continue
            date, precision = hd
            anchor = slug(heading)
            text = plain(body)
            label = ""
            m = self.label_rx.match(text)
            if m:
                label = m.group(1)
                text = text[m.end():].strip()
            links = []
            for _, href in MD_LINK.findall(body):
                u = urljoin(self.page_url, href)
                if u.startswith("http") and u not in links:
                    links.append(u)
            key = ""
            if links:
                p = urlparse(links[0])
                key = p.path + (f"#{p.fragment}" if p.fragment else "")
            sid = f"{self.page_url}#{anchor}::{key or slug(text)}"
            if sid in used:
                sid = f"{self.page_url}#{anchor}::{slug(text)}"
            used.add(sid)
            out.append(Update(
                technology=self.technology, source=self.id, source_id=sid, date=date,
                date_precision=precision, title=text, url=f"{self.page_url}#{anchor}",
                links=links, label=label, capability_hint=self.hint,
            ))
        return out
