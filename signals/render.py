"""Render the store into Docusaurus markdown.

Layout under the output dir (site/docs):
  index.md                       all technologies
  <tech>/_category_.json         sidebar section
  <tech>/index.md                capability list and latest updates
  <tech>/<capability>.md         every update for one capability, newest first

Files are .md, and the site uses markdown.format "detect", so they are parsed
as CommonMark, not MDX. Output is deterministic: no build timestamps.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from .classify import Taxonomy
from .model import Update
from .store import ordered

STATUS_LABEL = {
    "ga": ("GA", "success"),
    "public-preview": ("Public Preview", "primary"),
    "beta": ("Beta", "warning"),
    "private-preview": ("Private Preview", "secondary"),
    "experimental": ("Experimental", "secondary"),
}
KIND_LABEL = {
    "release": ("Release", "secondary"),
    "coming-soon": ("Coming soon", "info"),
    "deprecation": ("Deprecation", "danger"),
    "retirement": ("Retirement", "danger"),
}
SUMMARY_MAX = 220
LATEST_N = 25


def esc(text: str) -> str:
    """Make text safe inside a markdown table cell."""
    text = " ".join((text or "").split())
    return (text.replace("\\", "\\\\").replace("|", "\\|")
            .replace("<", "&lt;").replace(">", "&gt;"))


def esc_link_text(text: str) -> str:
    return esc(text).replace("[", "\\[").replace("]", "\\]")


def badge(label_map: dict, key: str) -> str:
    if not key:
        return ""
    label, color = label_map[key]
    return f'<span class="badge badge--{color}">{label}</span>'


def short(text: str, n: int = SUMMARY_MAX) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def update_cell(u: Update) -> str:
    cell = f"[{esc_link_text(u.title)}]({u.url})"
    extra = []
    if u.parent_title:
        extra.append(f"From: {esc(u.parent_title)}")
    if u.summary:
        extra.append(esc(short(u.summary)))
    if extra:
        cell += "<br/><small>" + "<br/>".join(extra) + "</small>"
    return cell


def docs_cell(u: Update) -> str:
    links = [link for link in u.links if link.split("#")[0] != u.url.split("#")[0]]
    return f"[docs]({links[0]})" if links else ""


def table(updates: list[Update], tax: Taxonomy | None = None, with_capability: bool = False) -> str:
    head = ["Date"] + (["Capability"] if with_capability else []) + ["Update", "Status", "Type", "Docs"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for u in updates:
        cells = [u.date]
        if with_capability:
            cap = tax.get(u.capability)
            cells.append(f"[{esc_link_text(cap.name)}](./{cap.id}.md)" if cap else esc(u.capability))
        cells += [update_cell(u), badge(STATUS_LABEL, u.status), badge(KIND_LABEL, u.kind), docs_cell(u)]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n"


def front(**kv) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in kv.items()] + ["---", ""]
    return "\n".join(lines)


def cap_order(tax: Taxonomy) -> list:
    caps = sorted((c for c in tax.capabilities if c.id != tax.default_capability), key=lambda c: c.name.lower())
    other = tax.get(tax.default_capability)
    return caps + ([other] if other else [])


def render_technology(out: Path, tax: Taxonomy, updates: dict[str, Update], position: int) -> dict:
    tdir = out / tax.technology
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    items = ordered(updates)
    by_cap: dict[str, list[Update]] = {}
    for u in items:
        by_cap.setdefault(u.capability, []).append(u)

    (tdir / "_category_.json").write_text(json.dumps({
        "label": tax.name, "position": position,
        "link": {"type": "doc", "id": f"{tax.technology}/index"},
    }, indent=2) + "\n", encoding="utf-8")

    caps = cap_order(tax)
    lines = [front(title=tax.name, sidebar_label="Overview", sidebar_position=0, slug=f"/{tax.technology}"),
             f"# {tax.name}\n",
             f"{len(items)} updates across {sum(1 for c in caps if by_cap.get(c.id))} capabilities.\n",
             "## Capabilities\n",
             "| Capability | Updates | Latest | GA | Public Preview | Beta |",
             "|---|---|---|---|---|---|"]
    for c in caps:
        us = by_cap.get(c.id, [])
        if not us:
            continue
        st = Counter(u.status for u in us)
        lines.append(f"| [{esc_link_text(c.name)}](./{c.id}.md) | {len(us)} | {us[0].date} "
                     f"| {st['ga']} | {st['public-preview']} | {st['beta']} |")
    lines += ["", f"## Latest {min(LATEST_N, len(items))} updates\n",
              table(items[:LATEST_N], tax, with_capability=True)]
    (tdir / "index.md").write_text("\n".join(lines), encoding="utf-8")

    for pos, c in enumerate(caps, start=1):
        us = by_cap.get(c.id, [])
        if not us:
            continue
        st = Counter(u.status for u in us)
        counts = ", ".join(f"{STATUS_LABEL[s][0]} {st[s]}" for s in STATUS_LABEL if st[s])
        body = [front(title=c.name, sidebar_position=pos, slug=f"/{tax.technology}/{c.id}"),
                f"# {c.name}\n"]
        if c.description:
            body.append(f"{c.description}\n")
        body.append(f"{len(us)} updates. Latest {us[0].date}." + (f" {counts}." if counts else "") + "\n")
        body.append(table(us))
        (tdir / f"{c.id}.md").write_text("\n".join(body), encoding="utf-8")

    return {"technology": tax.technology, "name": tax.name, "updates": len(items),
            "capabilities": sum(1 for c in caps if by_cap.get(c.id)),
            "latest": items[0].date if items else ""}


def render_home(out: Path, summaries: list[dict]) -> None:
    lines = [front(title="Signals", sidebar_label="Home", sidebar_position=0, slug="/"),
             "# Signals\n",
             "Product updates by technology and capability. Built daily from public sources by deterministic rules.\n",
             "| Technology | Capabilities | Updates | Latest |", "|---|---|---|---|"]
    for s in summaries:
        lines.append(f"| [{esc_link_text(s['name'])}](./{s['technology']}/index.md) | {s['capabilities']} | {s['updates']} | {s['latest']} |")
    lines.append("")
    lines.append("Status is the status the announcement gave on that date. "
                 "Type marks releases, coming-soon notices, deprecations and retirements.\n")
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")
