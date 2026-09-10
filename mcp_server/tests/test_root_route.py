"""The `/` route: a landing page for browsers, JSON for everything else."""

from __future__ import annotations

from starlette.testclient import TestClient

from mcp_server.config import Config
from mcp_server.server import build_app

_CFG = Config(
    domains=("AMO",), memgraph_uri="bolt://127.0.0.1:9", memgraph_user=None,
    memgraph_password=None, host="0.0.0.0", port=8000, allowed_hosts=(),
    rate_limit_max=60, rate_limit_window=60,
)


def test_root_serves_html_to_a_browser():
    app, graphs = build_app(_CFG)
    try:
        with TestClient(app) as c:
            r = c.get("/", headers={"accept": "text/html"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "<h1>" in r.text
        assert "github.com/Dickel/amo-situation-bench" in r.text
        assert "mcp.agenticgraph.net/amo/mcp" in r.text
        assert "{" not in r.text.split("<style>")[0]  # no unfilled .format placeholders
    finally:
        for g in graphs:
            g.close()


def test_root_serves_json_to_a_tool():
    # No Memgraph here, so healthz reports the domain as errored — but the shape
    # (JSON, not HTML) is what matters for a tool hitting `/`.
    app, graphs = build_app(_CFG)
    try:
        with TestClient(app) as c:
            r = c.get("/", headers={"accept": "application/json"})
        assert r.headers["content-type"].startswith("application/json")
        assert "endpoints" in r.json()
    finally:
        for g in graphs:
            g.close()
