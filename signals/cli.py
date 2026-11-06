"""Command line.

  python -m signals collect  [--tech ID] [--input COLLECTOR_ID=PATH ...]
  python -m signals classify [--tech ID]
  python -m signals render   [--out site/docs]
  python -m signals report   [--tech ID] [--other N]
  python -m signals all      collect, classify, render

Config: config/technologies.yaml lists technologies and their collectors.
Each technology has config/capabilities/<id>.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from . import collectors, store
from .classify import classify, load_taxonomy
from .render import render_home, render_technology

ROOT = Path(__file__).resolve().parent.parent


def load_config(root: Path) -> list[dict]:
    raw = yaml.safe_load((root / "config" / "technologies.yaml").read_text(encoding="utf-8"))
    return [t for t in raw["technologies"] if t.get("enabled", True)]


def pick(techs: list[dict], tech_id: str | None) -> list[dict]:
    if not tech_id:
        return techs
    found = [t for t in techs if t["id"] == tech_id]
    if not found:
        raise SystemExit(f"unknown technology {tech_id!r}")
    return found


def taxonomy(root: Path, tech_id: str):
    return load_taxonomy(root / "config" / "capabilities" / f"{tech_id}.yaml")


def reclassify(root: Path, data: Path, tech_id: str) -> dict:
    tax = taxonomy(root, tech_id)
    ups = store.load(data, tech_id)
    errors = []
    for u in ups.values():
        classify(tax, u)
        errors += [f"{u.id}: {e}" for e in u.validate()]
    if errors:
        raise SystemExit("invalid records:\n" + "\n".join(errors[:50]))
    store.save(data, tech_id, ups)
    return ups


def cmd_collect(args, root: Path, data: Path) -> None:
    inputs = dict(s.split("=", 1) for s in args.input or [])
    for t in pick(load_config(root), args.tech):
        tax = taxonomy(root, t["id"])
        ups = store.load(data, t["id"])
        for spec in t.get("collectors", []):
            col = collectors.build(t["id"], spec)
            new = col.collect(inputs.get(col.id))
            for u in new:
                classify(tax, u)
            bad = [(u, u.validate()) for u in new]
            bad = [(u, e) for u, e in bad if e]
            if bad:
                raise SystemExit(f"{col.id}: {len(bad)} invalid records, first: {bad[0][0].title!r}: {bad[0][1]}")
            ups, added, changed = store.merge(ups, new)
            print(json.dumps({"technology": t["id"], "collector": col.id, "items": len(new),
                              "added": added, "changed": changed}))
        store.save(data, t["id"], ups)
        reclassify(root, data, t["id"])


def cmd_classify(args, root: Path, data: Path) -> None:
    for t in pick(load_config(root), args.tech):
        ups = reclassify(root, data, t["id"])
        print(json.dumps({"technology": t["id"], "updates": len(ups)}))


def cmd_render(args, root: Path, data: Path) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for pos, t in enumerate(load_config(root), start=1):
        tax = taxonomy(root, t["id"])
        summaries.append(render_technology(out, tax, store.load(data, t["id"]), pos))
    render_home(out, summaries)
    print(json.dumps({"rendered": [s["technology"] for s in summaries], "out": str(out)}))


def cmd_report(args, root: Path, data: Path) -> None:
    for t in pick(load_config(root), args.tech):
        tax = taxonomy(root, t["id"])
        ups = store.ordered(store.load(data, t["id"]))
        caps = Counter(u.capability for u in ups)
        print(f"# {t['id']}: {len(ups)} updates")
        for c in tax.capabilities:
            print(f"  {caps.get(c.id, 0):5d}  {c.id}")
        print(f"  status: {dict(sorted(Counter(u.status or '-' for u in ups).items()))}")
        print(f"  kind:   {dict(sorted(Counter(u.kind for u in ups).items()))}")
        other = [u for u in ups if u.capability == tax.default_capability]
        print(f"  {tax.default_capability} (showing {min(args.other, len(other))} of {len(other)}):")
        for u in other[: args.other]:
            print(f"    {u.date}  {u.title}" + (f"  [in: {u.parent_title}]" if u.parent_title else "")
                  + (f"  {u.links[0]}" if u.links else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="signals")
    ap.add_argument("--root", default=str(ROOT), help="repo root holding config/")
    ap.add_argument("--data", default=None, help="data dir, default <root>/data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect")
    p.add_argument("--tech")
    p.add_argument("--input", action="append", help="COLLECTOR_ID=PATH, read a saved source instead of fetching")
    p = sub.add_parser("classify")
    p.add_argument("--tech")
    p = sub.add_parser("render")
    p.add_argument("--out", default=str(ROOT / "site" / "docs"))
    p = sub.add_parser("report")
    p.add_argument("--tech")
    p.add_argument("--other", type=int, default=50)
    p = sub.add_parser("all")
    p.add_argument("--tech", default=None)
    p.add_argument("--input", action="append")
    p.add_argument("--out", default=str(ROOT / "site" / "docs"))
    args = ap.parse_args(argv)
    root = Path(args.root)
    data = Path(args.data) if args.data else root / "data"
    if args.cmd == "collect":
        cmd_collect(args, root, data)
    elif args.cmd == "classify":
        cmd_classify(args, root, data)
    elif args.cmd == "render":
        cmd_render(args, root, data)
    elif args.cmd == "report":
        cmd_report(args, root, data)
    elif args.cmd == "all":
        cmd_collect(args, root, data)
        cmd_render(args, root, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
