"""Deterministic classifier. No model.

Reads config/capabilities/<technology>.yaml and sets capability, status and kind.

Capability, first match wins, stages in this order:
  1. capability_hint from the collector, if it names a known capability.
  2. parent_title (digest title) against each capability's `title` regexes.
  3. title against each capability's `title` regexes.
  4. each link, in order, turned into a docs path by `doc_path_pattern`,
     against each capability's `paths` prefixes.
  5. the taxonomy's `default_capability`.
Within a stage, capabilities are tried in file order. Put specific ones first.

Status: first `status_rules` regex that matches the title. No match means "".
Kind: first `kind_rules` regex that matches the title, then the first summary
sentence. No match means "release".

Taxonomies can override status_rules and kind_rules. The defaults below are
generic release vocabulary and name no product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import KINDS, STATUSES, Update

DEFAULT_STATUS_RULES = [
    ("ga", r"\bgenerally available\b|\bgeneral availability\b|\bis now ga\b|\bare now ga\b|\(ga\)|\bat ga\b"),
    ("public-preview", r"\bpublic preview\b"),
    ("private-preview", r"\bprivate preview\b"),
    ("beta", r"\(beta\)|\bin beta\b"),
    ("experimental", r"\bexperimental\b"),
]

DEFAULT_KIND_RULES = [
    ("retirement", r"\b(?:is|are|has been|have been) (?:now )?(?:retired|removed)\b"),
    ("deprecation", r"\bdeprecat|\bscheduled for retirement\b|\bend of (?:life|support)\b|\bend-of-life\b"
                    r"|\bupcoming (?:removal|retirement|end)\b|\bwill (?:soon )?be (?:retired|removed|rejected|deprecated)\b"
                    r"|\bno longer (?:be )?supported\b"),
    ("coming-soon", r"\bwill soon\b|\bsoon be\b|\bcoming soon\b|\bplans? to\b|\bupcoming\b"
                    r"|\bstarting in (?:january|february|march|april|may|june|july|august|september|october|november|december)\b"
                    r"|\bbeginning in\b"),
]


@dataclass
class Capability:
    id: str
    name: str
    description: str
    title: list[re.Pattern]
    paths: list[str]


@dataclass
class Taxonomy:
    technology: str
    name: str
    default_capability: str
    doc_path_pattern: re.Pattern | None
    capabilities: list[Capability]
    status_rules: list[tuple[str, re.Pattern]]
    kind_rules: list[tuple[str, re.Pattern]]

    def get(self, cap_id: str) -> Capability | None:
        return next((c for c in self.capabilities if c.id == cap_id), None)


def _rules(raw, allowed) -> list[tuple[str, re.Pattern]]:
    out = []
    for item in raw:
        value, rx = (item["value"], item["match"]) if isinstance(item, dict) else item
        if value not in allowed:
            raise ValueError(f"rule value {value!r} not in {allowed}")
        out.append((value, re.compile(rx, re.I)))
    return out


def load_taxonomy(path: Path) -> Taxonomy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    caps = []
    seen = set()
    for c in raw["capabilities"]:
        if c["id"] in seen:
            raise ValueError(f"{path}: duplicate capability id {c['id']}")
        seen.add(c["id"])
        caps.append(Capability(
            id=c["id"], name=c["name"], description=c.get("description", ""),
            title=[re.compile(rx, re.I) for rx in c.get("title", [])],
            paths=list(c.get("paths", [])),
        ))
    default = raw.get("default_capability", "other")
    if default not in seen:
        caps.append(Capability(default, "Other", "Updates no rule matched. Tune the taxonomy from this page.", [], []))
    pattern = raw.get("doc_path_pattern")
    return Taxonomy(
        technology=raw["technology"], name=raw.get("name", raw["technology"]),
        default_capability=default,
        doc_path_pattern=re.compile(pattern, re.I) if pattern else None,
        capabilities=caps,
        status_rules=_rules(raw.get("status_rules", DEFAULT_STATUS_RULES), STATUSES),
        kind_rules=_rules(raw.get("kind_rules", DEFAULT_KIND_RULES), KINDS),
    )


def doc_path(tax: Taxonomy, url: str) -> str | None:
    if not tax.doc_path_pattern:
        return None
    m = tax.doc_path_pattern.match(url)
    return m.group(1).strip("/") if m else None


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0] if text else ""


def capability_for(tax: Taxonomy, u: Update) -> str:
    if u.capability_hint and tax.get(u.capability_hint):
        return u.capability_hint
    for text in (u.parent_title, u.title):
        if not text:
            continue
        for c in tax.capabilities:
            if any(rx.search(text) for rx in c.title):
                return c.id
    for link in u.links:
        p = doc_path(tax, link)
        if p is None:
            continue
        for c in tax.capabilities:
            if any(p == pre.strip("/") or p.startswith(pre) for pre in c.paths):
                return c.id
    return tax.default_capability


def status_for(tax: Taxonomy, u: Update) -> str:
    return next((v for v, rx in tax.status_rules if rx.search(u.title)), "")


def kind_for(tax: Taxonomy, u: Update) -> str:
    for text in (u.title, first_sentence(u.summary)):
        for v, rx in tax.kind_rules:
            if rx.search(text):
                return v
    return "release"


def classify(tax: Taxonomy, u: Update) -> Update:
    u.capability = capability_for(tax, u)
    u.status = status_for(tax, u)
    u.kind = kind_for(tax, u)
    return u
