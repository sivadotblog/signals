# Signals

A doc site of product updates. One section per technology. One page per capability. Each page is one table of updates, newest first.

Site: https://sivadotblog.github.io/signals/

Collectors read sources such as RSS feeds and write normalized records. Fixed rules in a YAML file assign each record a capability, a status and a type. The renderer turns the records into Docusaurus pages. No model is involved. The same inputs always produce the same bytes.

## Layout

```
config/technologies.yaml            technologies and their collectors
config/capabilities/<tech>.yaml     capability taxonomy and matching rules
signals/model.py                    normalized Update record
signals/collectors/                 collector registry; rss.py, markdown_changelog.py, learn_page.py, snowflake_docs.py, common.py
signals/classify.py                 capability, status and type rules
signals/store.py                    data/<tech>/updates.jsonl
signals/render.py                   Docusaurus markdown
data/<tech>/updates.jsonl           collected records (committed; the store only grows)
site/                               Docusaurus site; site/docs/ is generated
.github/workflows/signals.yml       daily collect, commit data, build, deploy to Pages
```

## Record

Each update is one JSON line.

| Field | Set by | Meaning |
|---|---|---|
| `id` | framework | hash of `source` and `source_id` |
| `technology` | collector | technology id |
| `source`, `source_id` | collector | collector id, stable id inside the source |
| `date` | collector | announcement date, `YYYY-MM-DD` |
| `title`, `url`, `summary` | collector | announcement text and where to read it |
| `links` | collector | absolute URLs found in the item |
| `tags` | collector | source categories, if any |
| `parent_title` | collector | digest title, when one item was split into several updates |
| `capability_hint` | collector | only for product-specific sources |
| `label` | collector | status label the source states in its structure, e.g. a `Public Preview:` prefix |
| `date_precision` | collector | `day`, or `month` when the source gives only month and year (shown as `YYYY-MM`) |
| `capability` | classifier | capability id from the taxonomy |
| `status` | classifier | `ga`, `public-preview`, `beta`, `private-preview`, `experimental`, or empty |
| `kind` | classifier | `release`, `coming-soon`, `deprecation`, `retirement` |

Status is the status the announcement gave on its date. It is not the current status. A feature that went from Beta to GA has two rows.

Status and type are set only from words the vendor wrote as a label: "(Beta)", "is now generally available", "Public Preview:", "is retired", "end of life", "will soon". They are never inferred from verbs like "Adds" or "Removes", and never from summary text. No label means no status badge. It does not mean GA.

## Classification rules

For each record, the first match wins. Stages run in this order (a taxonomy can change it with `match_order`):

1. `hint`: `capability_hint`, if it names a known capability.
2. `parent_title`: digest or release title against each capability's `title` regexes.
3. `title`: item title against each capability's `title` regexes.
4. `tags`: source tags against each capability's `tags` list (exact, case-insensitive).
5. `links`: each link, turned into a docs path by `doc_path_pattern`, against each capability's `paths` prefixes. Links under `ignore_link_paths` are skipped.
6. `default_capability`, which is `other`.

Capabilities are tried top to bottom within a stage, so put specific ones above generic ones. Status comes from regexes over `label`, then the title. Type comes from regexes over the title. The defaults are in `signals/classify.py`, and a taxonomy can override them with `status_rules` and `kind_rules`.

To tune the rules, run the report and read the `other` list:

```
python -m signals classify
python -m signals report --tech databricks
```

## Run locally

```
pip install -e ".[dev]"
pytest -q
python -m signals collect                  # fetch all sources into data/ (a failing source is logged and skipped; --strict stops)
python -m signals render                   # write site/docs/
cd site && npm ci && npm start
```

Offline, with a saved feed:

```
python -m signals collect --input databricks-rss=tests/fixtures/databricks-feed.xml
```

## Sources

| Technology | Collector | Source |
|---|---|---|
| Databricks | `rss` | `learn.microsoft.com/en-us/azure/databricks/feed.xml`. Digest items are split into one row per bullet. |
| MongoDB | `markdown-changelog` | Each changelog listed on `mongodb.com/docs/atlas/release-notes/`, read as markdown (URL + `.md`). One row per bullet under a dated `###` heading. 2026 headings give only the month. Product changelogs pass `capability_hint`. |
| Azure Database for PostgreSQL | `learn-page` | The Learn release notes page, read as markdown through Learn's public MCP endpoint (`learn.microsoft.com/api/mcp`, fetch tool only, fixed URL). The source repo is private. Each run fetches twice and fails the source if the copies differ. Status comes from the group bullet ("General availability", "Preview") or an inline prefix. Dates are month only. |
| Snowflake | `snowflake-release-notes` | `docs.snowflake.com/en/release-notes/all-release-notes`. No RSS feed, and the `.md` copy is empty. The page embeds its entries as JSON in `__NEXT_DATA__`. Server releases are split into one row per feature. Keywords and change type become tags. |

## Add a technology

1. Add an entry to `config/technologies.yaml` with its collectors.
2. Add `config/capabilities/<id>.yaml`. Copy an existing file for the shape. Set `doc_path_pattern` for the docs URLs. If the vendor uses different status words, override `status_rules` (see the Snowflake file).
3. If the source is RSS, the `rss` collector type is enough. Otherwise add a collector:

```python
# signals/collectors/my_source.py
from ..model import Update
from . import register

@register("my-source")
class MySource:
    def __init__(self, technology: str, id: str, url: str):
        self.technology, self.id, self.url = technology, id, url

    def collect(self, input_path: str | None = None) -> list[Update]:
        ...  # return Update records; leave capability, status and kind to the classifier
```

Then import the new module at the bottom of `signals/collectors/__init__.py`.

Collector ids are part of every record id. Do not rename one after data exists. The same holds for how a collector builds `source_id`. If you change it, delete `data/<tech>/updates.jsonl` so the next run rebuilds the store. Otherwise old and new records both stay.

## GitHub Pages

In the repo settings, under Pages, set the source to "GitHub Actions". The workflow deploys on every run.
