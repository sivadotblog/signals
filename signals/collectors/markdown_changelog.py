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

Group labels: some pages group features under a status bullet,
  - General availability
      - Feature A
  - Preview
      - Feature B
With `group_label` set, a top-level bullet whose whole text matches it is not a row.
Each bullet nested under it becomes a row, with the group text as its label.

Params (from technologies.yaml):
  url              markdown URL
  page_url         human page URL for links, default: url without the .md suffix
  release_level    heading level of releases, default 3
  label_prefix     regex with one group for the label, default the common status words
  capability_hint  set on every record, for product-specific changelogs
  capability_fallback  set on every record; used only when no rule matches
  strip_md_links   turn same-site links to .md files into page links, default true
  heading_strip    regex removed from a heading before reading its date, e.g. '^Release:\\s*'
  group_label      regex; a top-level bullet that fully matches it is a status group
  strip_text       regex removed from every title, e.g. footnote markers
  item_level       heading level of items, for pages where each change is a heading
                   under the release heading (## May 2026 / ### Feature title / text).
                   The item heading is the title and the text under it the summary.
                   A release with no item headings uses its bullets as rows.
  page_url_slash   add a trailing slash to page_url when it has none, default true.
                   Turn off for sites whose pages have no trailing slash, so relative
                   links resolve against the page's folder.
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
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
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
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)  # *emphasis* and **bold**
    text = re.sub(r"(?<!\w)_{1,2}([^_]+)_{1,2}(?!\w)", r"\1", text)  # _emphasis_, not snake_case
    text = text.replace("`", "")
    return " ".join(text.split())


@register("markdown-changelog")
class MarkdownChangelog:
    def __init__(self, technology: str, id: str, url: str, page_url: str | None = None,
                 release_level: int = 3, label_prefix: str = DEFAULT_LABEL, capability_hint: str = "",
                 capability_fallback: str = "", strip_md_links: bool = True, heading_strip: str | None = None,
                 group_label: str | None = None, strip_text: str | None = None, page_url_slash: bool = True,
                 item_level: int | None = None):
        self.technology = technology
        self.id = id
        self.url = url
        self.page_url = page_url or re.sub(r"\.md$", "", url)
        if page_url_slash and not self.page_url.endswith("/") and not urlparse(self.page_url).path.rsplit("/", 1)[-1].count("."):
            self.page_url += "/"
        self.release_prefix = "#" * release_level + " "
        self.label_rx = re.compile(label_prefix, re.I)
        self.hint = capability_hint
        self.fallback = capability_fallback
        self.strip_md = strip_md_links
        self.host = urlparse(self.page_url).netloc
        self.heading_strip = re.compile(heading_strip, re.I) if heading_strip else None
        self.group_label = re.compile(group_label, re.I) if group_label else None
        self.strip_text = re.compile(strip_text) if strip_text else None
        self.item_level = item_level

    def page_link(self, u: str) -> str:
        """Markdown copies link to other .md copies. Point them at the HTML page instead."""
        p = urlparse(u)
        if self.strip_md and p.netloc == self.host and p.path.endswith(".md"):
            u = p._replace(path=p.path[:-3] + "/").geturl()
        return u

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
                cur.append(line.rstrip())
            elif cur is not None:
                yield heading, "\n".join(cur)  # unindented text ends the bullet
                cur = None
        if cur is not None and heading:
            yield heading, "\n".join(cur)

    def items(self, md: str):
        """Yield (heading, bullet markdown, group label) per row."""
        for heading, body in self.bullets(md):
            lines = body.split("\n")
            first = plain(lines[0])
            if self.group_label and self.group_label.fullmatch(first):
                for child in self.children(lines[1:]):
                    yield heading, child, first
            else:
                yield heading, body, ""

    @staticmethod
    def children(lines: list[str]) -> list[str]:
        """Split indented lines into the bullets at the shallowest nesting level."""
        bullets = [ln for ln in lines if BULLET.match(ln.lstrip())]
        if not bullets:
            return []
        depth = min(len(ln) - len(ln.lstrip()) for ln in bullets)
        out: list[list[str]] = []
        for ln in lines:
            ind = len(ln) - len(ln.lstrip())
            m = BULLET.match(ln.lstrip())
            if m and ind == depth:
                out.append([m.group(1)])
            elif out:
                out[-1].append(ln)
        return ["\n".join(c) for c in out]

    def heading_items(self, md: str):
        """Yield (release heading, item title, item body) for item_level pages."""
        rel_level = len(self.release_prefix) - 1
        release, title, body, release_had_items = None, None, [], False
        release_body: list[str] = []

        def flush_release():
            if release and not release_had_items:  # no item headings: bullets are the rows
                for b in self.children(release_body):
                    first, _, rest = b.partition("\n")
                    yield release, first, b
        for line in md.splitlines() + ["# end"]:
            hm = re.match(r"^(#{1,6})\s+(.*)$", line)
            if hm:
                level = len(hm.group(1))
                if title is not None:
                    yield release, title, "\n".join(body)
                    title, body = None, []
                if level == self.item_level and release:
                    title, release_had_items = hm.group(2).strip(), True
                    continue
                if level <= rel_level:
                    yield from flush_release()
                    release = hm.group(2).strip() if level == rel_level else None
                    release_had_items, release_body = False, []
                continue
            if title is not None:
                body.append(line)
            elif release:
                release_body.append(line)

    def parse(self, md: str) -> list[Update]:
        if self.item_level:
            return self.parse_heading_items(md)
        out: list[Update] = []
        used: set[str] = set()
        for heading, body, group in self.items(md):
            hd = heading_date(self.heading_strip.sub("", heading) if self.heading_strip else heading)
            if not hd:
                continue
            date, precision = hd
            anchor = slug(heading)
            text = plain(body)
            label = group
            m = self.label_rx.match(text)
            if m:
                label = label or m.group(1)
                text = text[m.end():].strip()
            if self.strip_text:
                text = " ".join(self.strip_text.sub(" ", text).split())
            links = []
            for _, href in MD_LINK.findall(body):
                u = self.page_link(urljoin(self.page_url, href))
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
                links=links, label=label, capability_hint=self.hint, capability_fallback=self.fallback,
            ))
        return out

    def parse_heading_items(self, md: str) -> list[Update]:
        out: list[Update] = []
        used: set[str] = set()
        for heading, title_md, body in self.heading_items(md):
            hd = heading_date(self.heading_strip.sub("", heading) if self.heading_strip else heading)
            if not hd:
                continue
            date, precision = hd
            title = plain(title_md)
            summary = plain(body)
            if self.strip_text:
                title = " ".join(self.strip_text.sub(" ", title).split())
            links = []
            for _, href in MD_LINK.findall(title_md + "\n" + body):
                u = self.page_link(urljoin(self.page_url, href))
                if u.startswith("http") and u not in links:
                    links.append(u)
            anchor = slug(heading)
            sid = f"{self.page_url}#{anchor}::{slug(title)}"
            n = 2
            while sid in used:
                sid = f"{self.page_url}#{anchor}::{slug(title)}-{n}"
                n += 1
            used.add(sid)
            out.append(Update(
                technology=self.technology, source=self.id, source_id=sid, date=date,
                date_precision=precision, title=title, url=f"{self.page_url}#{anchor}",
                summary=summary if summary != title else "", links=links,
                capability_hint=self.hint, capability_fallback=self.fallback,
            ))
        return out
