"""Microsoft Learn page collector.

Fetches a Learn page as markdown through Microsoft Learn's public MCP endpoint
(https://learn.microsoft.com/api/mcp, no auth), with its `microsoft_docs_fetch`
tool, then parses it with the markdown changelog parser.

Only the fetch tool is used, on URLs fixed in config. The search tool returns ranked
results and is never used here. The fetch tool converts the published page to
markdown on the server: the same page gives the same markdown. With `verify_stable`
(default true) the page is fetched twice and the run fails for this source if the
two copies differ.

Params (from technologies.yaml): every markdown-changelog param, plus
  url            the Learn page URL (also used as page_url)
  endpoint       MCP endpoint, default https://learn.microsoft.com/api/mcp
  verify_stable  fetch twice and compare, default true
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from ..model import Update
from . import register
from .common import UA
from .markdown_changelog import MarkdownChangelog

ENDPOINT = "https://learn.microsoft.com/api/mcp"
PROTOCOL = "2025-03-26"


def _decode(body: str, content_type: str) -> list[dict]:
    """JSON-RPC messages from a JSON or server-sent-events response body."""
    if "text/event-stream" in content_type or body.lstrip().startswith(("event:", "data:")):
        msgs, data = [], []
        for line in body.splitlines():
            if line.startswith("data:"):
                data.append(line[5:].strip())
            elif not line.strip() and data:
                msgs.append(json.loads("\n".join(data)))
                data = []
        if data:
            msgs.append(json.loads("\n".join(data)))
        return msgs
    return [json.loads(body)] if body.strip() else []


class LearnMcp:
    """Minimal MCP client over streamable HTTP: initialize, then call one tool."""

    def __init__(self, endpoint: str = ENDPOINT):
        self.endpoint = endpoint
        self.session: str | None = None
        self.next_id = 1

    def _post(self, payload: dict) -> list[dict]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": UA, "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            return _decode(r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", ""))

    def _request(self, method: str, params: dict) -> dict:
        rid = self.next_id
        self.next_id += 1
        for msg in self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}):
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"MCP {method} error: {msg['error']}")
                return msg["result"]
        raise RuntimeError(f"MCP {method}: no response with id {rid}")

    def connect(self) -> None:
        self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "signals", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def fetch(self, url: str) -> str:
        res = self._request("tools/call", {"name": "microsoft_docs_fetch", "arguments": {"url": url}})
        if res.get("isError"):
            raise RuntimeError(f"microsoft_docs_fetch failed for {url}: {res.get('content')}")
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if not text.strip():
            raise RuntimeError(f"microsoft_docs_fetch returned no text for {url}")
        return text


def fetch_markdown(url: str, endpoint: str = ENDPOINT, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            client = LearnMcp(endpoint)
            client.connect()
            return client.fetch(url)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Learn MCP fetch failed: {url}: {last}")


@register("learn-page")
class LearnPage(MarkdownChangelog):
    def __init__(self, technology: str, id: str, url: str, endpoint: str = ENDPOINT,
                 verify_stable: bool = True, **params):
        params.setdefault("page_url_slash", False)  # Learn pages have no trailing slash
        super().__init__(technology=technology, id=id, url=url, page_url=params.pop("page_url", url), **params)
        self.endpoint = endpoint
        self.verify_stable = verify_stable

    def collect(self, input_path: str | None = None) -> list[Update]:
        if input_path:
            return self.parse(Path(input_path).read_text(encoding="utf-8"))
        md = fetch_markdown(self.url, self.endpoint)
        if self.verify_stable:
            again = fetch_markdown(self.url, self.endpoint)
            h1, h2 = (hashlib.sha256(x.encode()).hexdigest()[:12] for x in (md, again))
            if h1 != h2:
                raise RuntimeError(f"{self.id}: two fetches differ ({h1} != {h2}); output is not stable")
            print(json.dumps({"collector": self.id, "stable": True, "sha256": h1}))
        return self.parse(md)
