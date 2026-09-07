"""include_cypher parity guard.

`include_cypher` must do exactly one thing: decide whether the `cypher` key is
attached. For every tool, the `include_cypher=False` response must equal the
`include_cypher=True` response with the `cypher` key removed — never a shorter
payload, never a missing array.

This exercises the real registered tool functions (through `build_domain_server`
+ `call_tool`) against a live Memgraph. Skipped when Memgraph is unreachable.
A standalone variant that hits a *deployed* server is in
`mcp_server/tests/parity_deployed.py`.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from mcp_server.config import Config
from mcp_server.graph import GraphClient, _stack_is_incoherent
from mcp_server.server import build_domain_server

URI = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")

# tool -> kwargs (minus include_cypher). Ids are the seeded synthetic instances.
CASES = {
    "list_situation_types": {},
    "get_stack_model": {},
    "get_strategies": {"situation_id": "SIT-AMO-001"},
    "explain_qualifier": {"situation_id": "SIT-AMO-001"},
    "match_situations": {"entity_id": "WO-4471"},
    "get_situation_footprint": {"situation_id": "SIT-AMO-001"},
    "get_skill": {"situation_id": "SIT-AMO-001"},
    "read_commitments": {"entity_id": "SIT-AMO-004"},
    "read_order_context": {"work_order_id": "WO-4471"},
}


def _cfg(domain: str) -> Config:
    return Config(
        domains=(domain,), memgraph_uri=URI, memgraph_user=None, memgraph_password=None,
        host="0.0.0.0", port=8000, allowed_hosts=(), rate_limit_max=10_000, rate_limit_window=60,
    )


@pytest.fixture
def server():
    domain = "AMO"
    try:
        g = GraphClient(domain, URI)
        g.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Memgraph at {URI}: {exc}")
    srv = build_domain_server(domain, g, _cfg(domain))
    yield domain, srv
    g.close()


def _call(srv, tool: str, **kw) -> dict:
    res = asyncio.run(srv.call_tool(tool, kw))
    return json.loads(res.content[0].text)


def test_include_cypher_only_toggles_the_cypher_key(server):
    domain, srv = server
    cases = CASES
    failures = []
    for tool, kw in cases.items():
        with_c = _call(srv, tool, include_cypher=True, **kw)
        without = _call(srv, tool, include_cypher=False, **kw)
        assert "cypher" in with_c, f"{domain}/{tool}: include_cypher=True did not attach `cypher`"
        assert "cypher" not in without, f"{domain}/{tool}: include_cypher=False leaked `cypher`"
        with_c.pop("cypher", None)
        if with_c != without:
            diff = sorted(k for k in set(with_c) | set(without) if with_c.get(k) != without.get(k))
            failures.append(f"{domain}/{tool}: {diff or 'nested values differ'}")
    assert not failures, "include_cypher changed more than the `cypher` key:\n  " + "\n  ".join(failures)


def test_stack_incoherence_guard():
    # has_graph true + zero systems == mid-reload / incomplete load -> explicit error
    assert _stack_is_incoherent(True, []) is True
    assert _stack_is_incoherent(True, [{"system_class": "ERP"}]) is False
    assert _stack_is_incoherent(False, []) is False   # spec-table model, legitimately no :System nodes


def test_get_stack_model_false_path_has_the_full_payload(server):
    domain, srv = server
    r = _call(srv, "get_stack_model", include_cypher=False)
    assert "cypher" not in r
    assert r.get("systems"), f"{domain}: systems empty on the include_cypher=False path"
    if r.get("has_graph"):
        for key in ("data_objects", "business_processes", "standards", "example_queries"):
            assert key in r, f"{domain}: {key} missing on the include_cypher=False path"
        assert all(bs.get("systems") for bs in r["known_blind_spots"]), \
            f"{domain}: a known_blind_spot lost its systems pair"
