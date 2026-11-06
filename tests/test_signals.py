import filecmp
import shutil
from pathlib import Path

import pytest

from signals import store
from signals.classify import load_taxonomy, classify
from signals.cli import load_config, main
from signals.collectors import build
from signals.model import Update

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "databricks-feed.xml"
TAX = load_taxonomy(ROOT / "config" / "capabilities" / "databricks.yaml")


def collect_fixture():
    spec = next(c for t in load_config(ROOT) if t["id"] == "databricks" for c in t["collectors"])
    col = build("databricks", spec)
    return [classify(TAX, u) for u in col.collect(str(FIXTURE))]


def by_title(ups):
    return {u.title: u for u in ups}


def test_digest_is_split_and_uses_parent_title():
    ups = by_title(collect_fixture())
    u = ups["Analyze files in Unity Catalog volumes (Public Preview)"]
    assert u.parent_title == "Genie Agents enhancements"
    assert u.capability == "genie-agents"  # parent title wins over "Unity Catalog" in the bullet
    assert u.status == "public-preview"
    assert u.links == ["https://learn.microsoft.com/azure/databricks/genie-agents/volumes"]
    assert "Genie Agents enhancements" not in ups  # parent itself is not a row
    assert ups["Agent memory"].status == ""


def test_status_kind_capability():
    ups = by_title(collect_fixture())
    lb = ups["Lakebase snapshots and backup schedule APIs are generally available"]
    assert (lb.capability, lb.status, lb.kind, lb.date) == ("lakebase", "ga", "release", "2026-10-26")
    ok = ups["Okta connector is available in Beta"]
    assert (ok.capability, ok.status) == ("lakeflow-connect", "beta")
    ds = ups["DeepSeek V4 Flash (0731) is retired"]
    assert (ds.capability, ds.kind) == ("unity-gateway", "retirement")
    gs = ups["Genie Ontology snippets will soon be generally available and enabled by default"]
    assert (gs.capability, gs.status, gs.kind) == ("genie", "ga", "coming-soon")


def test_path_fallback_and_default():
    ups = by_title(collect_fixture())
    assert ups["Something with no matching rule"].capability == "lakebase"  # via oltp/ docs link
    assert ups["Truly unmatched item"].capability == "other"


@pytest.mark.parametrize("title,status", [
    ("Lakebase Search is generally available", "ga"),
    ("Databricks CLI is now GA", "ga"),
    ("New `INSERT REPLACE` commands (GA)", "ga"),
    ("Lakebase Change Data Feed (CDF) is now in Public Preview", "public-preview"),
    ("Lakebase now available on Azure (Beta)", "beta"),
    ("Omnigent coding agent meta-harness is now in Beta", "beta"),
    ("Lakebase now available in five additional Azure regions", ""),
    ("Account-level security features are now available by default at GA", "ga"),
])
def test_status_rules(title, status):
    u = classify(TAX, Update("databricks", "t", title, "2026-01-01", title, "https://x"))
    assert u.status == status


@pytest.mark.parametrize("title,kind", [
    ("DeepSeek V4.1 Flash is scheduled for retirement", "deprecation"),
    ("Upcoming end of life for the Genie One MCP Beta endpoint", "deprecation"),
    ("Thinking Machine Labs Inkling is retired", "retirement"),
    ("Azure Databricks plans to support Tableau as a source", "coming-soon"),
    ("Okta connector is available in Beta", "release"),
])
def test_kind_rules(title, kind):
    u = classify(TAX, Update("databricks", "t", title, "2026-01-01", title, "https://x"))
    assert u.kind == kind


def test_records_valid_and_ids_stable():
    a, b = collect_fixture(), collect_fixture()
    assert [u.id for u in a] == [u.id for u in b]
    assert len({u.id for u in a}) == len(a)
    for u in a:
        assert u.validate() == [], u.title


def test_store_merge_keeps_old_records(tmp_path):
    ups = collect_fixture()
    s, added, _ = store.merge({}, ups)
    assert added == len(ups)
    store.save(tmp_path, "databricks", s)
    s2, added2, changed2 = store.merge(store.load(tmp_path, "databricks"), ups[:2])
    assert (added2, changed2, len(s2)) == (0, 0, len(ups))


def run_pipeline(tmp: Path, out: Path):
    data = tmp / "data"
    args = ["--data", str(data), "all", "--input", f"databricks-rss={FIXTURE}", "--out", str(out)]
    assert main(args) == 0
    return data


def test_end_to_end_is_deterministic(tmp_path):
    d1 = run_pipeline(tmp_path / "a", tmp_path / "out1")
    d2 = run_pipeline(tmp_path / "b", tmp_path / "out2")
    assert (d1 / "databricks" / "updates.jsonl").read_bytes() == (d2 / "databricks" / "updates.jsonl").read_bytes()
    cmp = filecmp.dircmp(tmp_path / "out1", tmp_path / "out2")
    assert not cmp.diff_files and not cmp.left_only and not cmp.right_only
    # Second run over the same store changes nothing.
    run_pipeline(tmp_path / "a", tmp_path / "out1")
    assert (d1 / "databricks" / "updates.jsonl").read_bytes() == (d2 / "databricks" / "updates.jsonl").read_bytes()


def test_render_page_shape(tmp_path):
    out = tmp_path / "out"
    run_pipeline(tmp_path, out)
    page = (out / "databricks" / "genie-agents.md").read_text()
    assert 'slug: "/databricks/genie-agents"' in page
    assert "| Date | Update | Status | Type | Docs |" in page
    assert "From: Genie Agents enhancements" in page
    genie = (out / "databricks" / "genie.md").read_text()
    assert "\\|" in genie and "&lt;tag&gt;" in genie  # cell text escaped
    lb = (out / "databricks" / "lakebase.md").read_text().splitlines()
    rows = [line for line in lb if line.startswith("| 2026")]
    assert [r.split(" | ")[0] for r in rows] == sorted([r.split(" | ")[0] for r in rows], reverse=True)
    assert (out / "databricks" / "other.md").exists()
    assert not (out / "databricks" / "vector-search.md").exists()  # empty capabilities get no page
    assert (out / "index.md").exists() and (out / "databricks" / "_category_.json").exists()
    shutil.rmtree(out)


def test_no_product_names_in_core():
    for p in (ROOT / "signals").rglob("*.py"):
        text = p.read_text().lower()
        assert "lakebase" not in text, p


def test_split_guards_and_ignored_links():
    ups = by_title(collect_fixture())
    d = ups["Discover page and domains (Beta)"]  # status in title: kept whole
    assert d.parent_title == "" and d.status == "beta"
    assert d.capability == "unity-catalog"  # release-types link skipped, discover/ link used
    assert TAX.content_links(d.links) == ["https://learn.microsoft.com/azure/databricks/discover/"]
    assert "Connect and govern any external model provider" in ups  # one-word bullets: kept whole
    assert "Control" not in ups
