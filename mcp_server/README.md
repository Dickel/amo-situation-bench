# mcp_server

Curated, read-only MCP tool surface over the situation graph. Streamable-HTTP
transport. The only publicly reachable part of the deployment.

Live: **https://mcp.agenticgraph.net/amo/mcp**

## Structure

Each domain in `DOMAINS` (default `AMO`) is served as an independent `MCPServer`
at its own path (`/amo/mcp`). A client on `/amo/mcp` only ever sees AMO — the
per-path isolation is the seam for adding another domain. Tools are not
parameterised by domain; the endpoint already is.

## Tools

| Tool | Returns |
|---|---|
| `list_situation_types` | the catalog: id, name, trigger condition, classification, `detectability`, `detected_by_system_class` |
| `match_situations(entity_id)` | which situation types the given instance id currently triggers (runs each stored `trigger.pattern`), with matched ids |
| `get_strategies(situation_id)` | `solver_boundary`, plus each strategy with preconditions, trade-off, `system_of_action` (write path, `reversibility`, `authority`), `delegation_ceiling`, any `known_limitation` |
| `explain_qualifier(situation_id)` | classification, practitioner divergence, rationale, `solver_boundary`, and (where the trigger reasons about time) `temporal_semantics` + `tracked_transitions` |
| `get_stack_model` | the reference model — `systems` (with `write_semantics`), `interfaces`, `known_blind_spots`, `data_objects`, `business_processes`, `standards`, `example_queries` |
| `get_situation_footprint(situation_id)` | which systems a situation spans: `detected_by`, `evidence_systems`, `acts_on_systems`, `covers_blind_spots`, `cross_system_enforcement` |
| `get_skill(situation_id)` | the SKILL.md operating envelope for a situation; empty id / `"triage"` → the cross-cutting triage skill |
| `read_commitments(id)` | the customer commitments a situation or work order is exposed to — customer, tier, commit/need dates, partial-shipment stance |
| `read_order_context(work_order_id)` | everything the graph holds about one work order: fields + provenance, required parts, operations, build/programme, commitment, involving situations |

`include_cypher` (default on) attaches the exact query text that ran — a teaching
feature. It does **exactly one thing**: decide whether the `cypher` key is
present; the response is otherwise byte-identical.
`mcp_server/tests/test_include_cypher_parity.py` guards this across every tool
in-process; `mcp_server/tests/parity_deployed.py` runs it against a deployed
server (copy `deploy/parity-ci.yml` to `.github/workflows/` to run it in CI).

Read-only. No tool accepts free Cypher. `match_situations` is the one place
stored query text runs — the loader-written `trigger.pattern` strings, scoped to
the endpoint's domain (`{domain: $domain}` inline in every pattern, `domain`
passed as a parameter).

Rate limited (`RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW`, default 60/60s per client
IP) — a runaway-client guard, not a security boundary. No auth; synthetic data.

## Run locally

```bash
pip install -r mcp_server/requirements.txt
# Memgraph must be seeded (see loader/)
MEMGRAPH_URI=bolt://127.0.0.1:7687 MCP_PORT=8899 python -m mcp_server
# -> http://localhost:8899/amo/mcp ,  health at /healthz
```

Tests: `MEMGRAPH_URI=bolt://127.0.0.1:7687 pytest mcp_server` (graph tests skip
without Memgraph; rate-limiter tests always run).

## Deploy

Plain `python:3.12-slim` image (`deploy/Dockerfile`), does not bundle Memgraph.
From the repo root: `fly deploy -c fly.mcp.toml`. Reaches Memgraph over Fly's
private network; `min_machines_running = 0` (cold-start is fine).
