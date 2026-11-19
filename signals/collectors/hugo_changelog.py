"""Hugo changelog collector.

For vendors whose docs site is built with Hugo from a public GitHub repo, with one
markdown file per month. The markdown sources are read from GitHub, because the
published HTML has no markdown copy or feed. Records link to the published site.

Layout it expects, one file per month (e.g. content/operate/rc/changelog/september-2026.md):

  ---
  linktitle: September 2026            month of the page (front matter `date_field`)
  tags: [changelog]                    pages without `page_tag` are skipped
  ---
  ## New features                      category heading (release_level), becomes a tag
  ### Redis Search on Flex (beta)      one change per item heading (item_level)
  text, bullets, #### sub-headings     the item's summary
  ## Deprecations
  - bullet                             a category with no item headings: one row per bullet

Older months may sit in sub-folders (2023/, 2024/). Sub-folders whose name matches
`subdir_include` are read too. Index pages (`_index.md`) and pages whose date field
does not parse as a month are skipped.

Each change becomes one Update:
  title      item heading (or bullet text), plain text
  date       first day of the page's month, date_precision "month"
  url        published page URL plus the heading anchor Hugo generates
  tags       the category heading, e.g. "New features", "Deprecations"
  links      every link in the item, absolute. Hugo source links like
             /content/operate/rc/x/_index.md#a become site URLs; image links are dropped.
  source_id  page path + category + title

Params (from technologies.yaml):
  repo            GitHub owner/name holding the Hugo sources
  path            folder of the changelog pages inside the repo
  ref             branch, default main
  site_url        published URL of the Hugo content root (content/ in the repo)
  content_dir     repo folder that maps to site_url, default content
  page_tag        front matter tag a changelog page must carry, default changelog
  date_field      front matter field with the page's month, default linktitle
  subdir_include  regex on sub-folder names to read, default four-digit years
  release_level, item_level   category and item heading levels, default 2 and 3

The folder is listed through the GitHub contents API (one call per folder). Set
GITHUB_TOKEN to raise the API rate limit. Offline, `input_path` is a local copy of
`path` with the same layout.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import yaml

from ..model import Update
from . import register
from .common import UA, fetch, slug
from .markdown_changelog import MD_LINK, MarkdownChangelog, heading_date, plain

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
SHORTCODE = re.compile(r"\{\{[<%].*?[%>]\}\}", re.S)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def hugo_anchor(text: str) -> str:
    """Heading id as Hugo's default (GitHub style) generator makes it."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def split_front_matter(md: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(md)
    if not m:
        return {}, md
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), md[m.end():]


def _get_json(url: str, retries: int = 3):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


@register("hugo-changelog")
class HugoChangelog:
    def __init__(self, technology: str, id: str, repo: str, path: str, site_url: str, ref: str = "main",
                 content_dir: str = "content", page_tag: str = "changelog", date_field: str = "linktitle",
                 subdir_include: str = r"^\d{4}$", release_level: int = 2, item_level: int = 3):
        self.technology = technology
        self.id = id
        self.repo = repo
        self.path = path.strip("/")
        self.ref = ref
        self.site_url = site_url.rstrip("/") + "/"
        self.content_dir = content_dir.strip("/")
        self.page_tag = page_tag
        self.date_field = date_field
        self.subdir_rx = re.compile(subdir_include)
        self.release_level = release_level
        self.item_level = item_level
        self.url = f"https://github.com/{repo}/tree/{ref}/{self.path}"

    # Sources

    def remote_pages(self) -> list[tuple[str, str]]:
        """(repo path, markdown) per .md file in path and its matching sub-folders."""
        out, folders = [], [self.path]
        while folders:
            folder = folders.pop()
            api = f"https://api.github.com/repos/{self.repo}/contents/{folder}?ref={self.ref}"
            for e in _get_json(api):
                if e["type"] == "dir" and self.subdir_rx.search(e["name"]):
                    folders.append(e["path"])
                elif e["type"] == "file" and e["name"].endswith(".md") and e["name"] != "_index.md":
                    out.append((e["path"], e["download_url"]))
        return [(p, fetch(u)) for p, u in sorted(out)]

    def local_pages(self, root: Path) -> list[tuple[str, str]]:
        out = []
        for f in sorted(root.rglob("*.md")):
            rel = f.relative_to(root)
            if f.name == "_index.md" or not all(self.subdir_rx.search(d) for d in rel.parts[:-1]):
                continue
            out.append((f"{self.path}/{rel.as_posix()}", f.read_text(encoding="utf-8")))
        return out

    def collect(self, input_path: str | None = None) -> list[Update]:
        pages = self.local_pages(Path(input_path)) if input_path else self.remote_pages()
        out: list[Update] = []
        for repo_path, md in pages:
            out += self.parse_page(repo_path, md)
        if not out:
            raise RuntimeError(f"{self.id}: no changelog entries found under {self.url}")
        return out

    # Parsing

    def page_url(self, repo_path: str) -> str:
        rel = repo_path[len(self.content_dir) + 1:] if repo_path.startswith(self.content_dir + "/") else repo_path
        rel = re.sub(r"(?:/_index)?\.md$", "", rel)
        return self.site_url + rel + "/"

    def site_link(self, href: str, page_url: str) -> str:
        """Hugo source links (/content/a/b.md#x) to published URLs (site/a/b/#x)."""
        prefix = f"/{self.content_dir}/"
        if not href.startswith(prefix):
            return urljoin(page_url, href)
        rest, frag = (href[len(prefix):].split("#", 1) + [""])[:2]
        rest, query = (rest.split("?", 1) + [""])[:2]
        rest = re.sub(r"(?:/?_index)?\.md$", "", rest).strip("/")
        u = self.site_url + (rest + "/" if rest else "")
        return u + (f"?{query}" if query else "") + (f"#{frag}" if frag else "")

    def parse_page(self, repo_path: str, md: str) -> list[Update]:
        fm, body = split_front_matter(md)
        tags = fm.get("tags") or []
        if self.page_tag and self.page_tag not in tags:
            return []
        hd = heading_date(str(fm.get(self.date_field, "")))
        if not hd:
            return []  # year index pages and the like
        date, precision = hd
        page_url = self.page_url(repo_path)
        parser = MarkdownChangelog(self.technology, self.id, url=page_url, page_url=page_url,
                                   release_level=self.release_level, item_level=self.item_level)
        out: list[Update] = []
        used: set[str] = set()
        for section, title_md, item_md in parser.heading_items(SHORTCODE.sub(" ", body)):
            category = plain(section)
            title = plain(re.sub(r"^[-*+]\s+", "", title_md))
            if not title:
                continue
            is_heading = title_md != item_md.split("\n", 1)[0]  # bullet rows carry their own first line
            summary = plain(IMAGE.sub(" ", item_md))
            links = []
            for _, href in MD_LINK.findall(IMAGE.sub(" ", title_md + "\n" + item_md)):
                u = self.site_link(href, page_url)
                if u.startswith("http") and u not in links:
                    links.append(u)
            anchor = hugo_anchor(title if is_heading else category)
            sid = f"{repo_path}::{slug(category)}::{slug(title)}"
            n = 2
            while sid in used:
                sid = f"{repo_path}::{slug(category)}::{slug(title)}-{n}"
                n += 1
            used.add(sid)
            out.append(Update(
                technology=self.technology, source=self.id, source_id=sid, date=date,
                date_precision=precision, title=title, url=f"{page_url}#{anchor}",
                summary="" if summary == title else summary, links=links, tags=[category],
            ))
        return out
