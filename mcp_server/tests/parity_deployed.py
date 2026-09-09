"""include_cypher parity guard — against a *deployed* server (not a unit test).

    python -m mcp_server.tests.parity_deployed
    python -m mcp_server.tests.parity_deployed --url https://staging.example/amo/mcp

Asserts, for every tool: response(include_cypher=False) equals
response(include_cypher=True) minus the `cypher` key. Exits non-zero on any
mismatch. Wired into CI (`.github/workflows/parity.yml`) against the deployed
instance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

DEFAULT_URL = "https://mcp.agenticgraph.net/amo/mcp"

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


async def call(url: str, tool: str, **kw) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(tool, kw)
    return json.loads(res.content[0].text)


async def check(url: str, tool: str, kw: dict) -> tuple[bool, str]:
    try:
        t = await call(url, tool, include_cypher=True, **kw)
        f = await call(url, tool, include_cypher=False, **kw)
    except Exception as e:  # noqa: BLE001
        return False, f"call failed: {e}"
    if "cypher" not in t:
        return False, "include_cypher=True did not attach `cypher`"
    if "cypher" in f:
        return False, "include_cypher=False leaked `cypher`"
    t.pop("cypher", None)
    if t == f:
        return True, ""
    diff = sorted(k for k in set(t) | set(f) if t.get(k) != f.get(k))
    return False, f"fields differ: {', '.join(diff) or 'nested values'}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    a = ap.parse_args()

    failed = 0
    print(a.url)
    for tool, kw in CASES.items():
        ok, msg = await check(a.url, tool, kw)
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {tool}" + (f"  <- {msg}" if msg else ""))
    print(f"\n{failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
