"""Helpers shared by collectors: fetching, HTML to text, links, digest splitting."""

from __future__ import annotations

import re
import time
import urllib.request
from html import unescape
from urllib.parse import urljoin

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
    text = " ".join(unescape(TAG_RE.sub(" ", html or "")).split())
    text = re.sub(r"\s+([.,;:!?)])", r"\1", text)  # tags leave a space before punctuation
    return re.sub(r"\(\s+", "(", text)  # and after an opening parenthesis


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def links_in(html: str, base: str) -> list[str]:
    out = []
    for href in HREF_RE.findall(html or ""):
        u = urljoin(base, unescape(href))
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


class DigestSplitter:
    """Split an item whose body lists features as <li><strong>Title</strong>: text</li>.

    no_split_title   regex; never split items whose title matches (one announcement
                     with a status that lists its parts as bullets)
    no_split_bullet  regex; never split if any bullet title matches (timeline bullets)
    split_min_words  every bullet title needs at least this many words, default 2
    """

    def __init__(self, enabled: bool = False, no_split_title: str | None = None,
                 no_split_bullet: str | None = None, split_min_words: int = 2):
        self.enabled = enabled
        self.no_split_title = re.compile(no_split_title, re.I) if no_split_title else None
        self.no_split_bullet = re.compile(no_split_bullet, re.I) if no_split_bullet else None
        self.split_min_words = split_min_words

    def parts(self, title: str, html: str) -> list[tuple[str, str, str]]:
        """(bullet title, bullet body html, bullet html) per bullet, or [] to keep the item whole."""
        if not self.enabled or (self.no_split_title and self.no_split_title.search(title)):
            return []
        parts = []
        for li in LI_RE.findall(html or ""):
            m = DIGEST_LI_RE.match(li)
            if m:
                parts.append((text_of(m.group(2)).rstrip(":").strip(), m.group(3), li))
        for sub_title, _, _ in parts:
            if len(sub_title.split()) < self.split_min_words:
                return []
            if self.no_split_bullet and self.no_split_bullet.search(sub_title):
                return []
        return parts
