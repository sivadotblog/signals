"""Normalized update record shared by every collector.

A collector turns its source into Update records. It fills the source fields.
The classifier fills `capability`, `status` and `kind` from the technology's
taxonomy file. Collectors never decide those three fields, except through
`capability_hint`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

STATUSES = ("ga", "public-preview", "beta", "private-preview", "experimental")
KINDS = ("release", "coming-soon", "deprecation", "retirement")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Update:
    # Source fields. Set by the collector.
    technology: str  # technology id, e.g. "databricks"
    source: str  # collector id, e.g. "databricks-rss"
    source_id: str  # stable id inside the source, e.g. feed guid
    date: str  # YYYY-MM-DD
    title: str
    url: str  # where to read the announcement
    summary: str = ""  # plain text
    links: list[str] = field(default_factory=list)  # absolute URLs found in the item
    tags: list[str] = field(default_factory=list)  # source categories, if any
    parent_title: str = ""  # digest title when one source item was split into several updates
    capability_hint: str = ""  # set only when the source itself is product-specific
    capability_fallback: str = ""  # used instead of default_capability when no rule matches
    label: str = ""  # status label the source states in its structure, e.g. a "Public Preview:" prefix
    date_precision: str = "day"  # "day", or "month" when the source gives only month and year

    # Classifier fields. Set by signals.classify.
    capability: str = ""
    status: str = ""  # one of STATUSES, or "" when the text names no status
    kind: str = "release"  # one of KINDS

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}\n{self.source_id}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = {"id": self.id, **asdict(self)}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Update":
        d = {k: v for k, v in d.items() if k != "id"}
        return cls(**d)

    def validate(self) -> list[str]:
        errs = []
        for name in ("technology", "source", "source_id", "title", "url"):
            if not getattr(self, name):
                errs.append(f"{name} is empty")
        if not DATE_RE.match(self.date or ""):
            errs.append(f"date {self.date!r} is not YYYY-MM-DD")
        if self.status and self.status not in STATUSES:
            errs.append(f"status {self.status!r} not in {STATUSES}")
        if self.date_precision not in ("day", "month"):
            errs.append(f"date_precision {self.date_precision!r} not in ('day', 'month')")
        if self.kind not in KINDS:
            errs.append(f"kind {self.kind!r} not in {KINDS}")
        return errs
