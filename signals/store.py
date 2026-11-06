"""JSONL store, one file per technology: data/<technology>/updates.jsonl.

The store only grows. Feeds keep a limited window, so records that drop out of a
feed stay here. A record with the same id is replaced by the newer copy.
Output is sorted and has no run timestamps, so the same inputs give the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Update


def path_for(data_dir: Path, technology: str) -> Path:
    return data_dir / technology / "updates.jsonl"


def load(data_dir: Path, technology: str) -> dict[str, Update]:
    p = path_for(data_dir, technology)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            u = Update.from_dict(json.loads(line))
            out[u.id] = u
    return out


def merge(existing: dict[str, Update], new: list[Update]) -> tuple[dict[str, Update], int, int]:
    added = changed = 0
    for u in new:
        old = existing.get(u.id)
        if old is None:
            added += 1
        elif old.to_dict() != u.to_dict():
            changed += 1
        existing[u.id] = u
    return existing, added, changed


def ordered(updates: dict[str, Update] | list[Update]) -> list[Update]:
    items = list(updates.values()) if isinstance(updates, dict) else list(updates)
    # Newest first. Ties broken by source order fields so the result is stable.
    return sorted(items, key=lambda u: (u.date, u.source, u.source_id), reverse=True)


def save(data_dir: Path, technology: str, updates: dict[str, Update]) -> Path:
    p = path_for(data_dir, technology)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(u.to_dict(), ensure_ascii=False, sort_keys=True) for u in ordered(updates)]
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return p


def save_health(data_dir: Path, technology: str, health: dict) -> Path:
    """Per-collector item count and last error from the latest live run."""
    p = data_dir / technology / "sources.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def load_health(data_dir: Path, technology: str) -> dict:
    p = data_dir / technology / "sources.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
