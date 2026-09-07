"""One process, one MCP server per domain, each at its own path — /amo/mcp.

Every domain in DOMAINS is mounted as an independent MCPServer that registers
only that domain's tools and only queries that domain's nodes. This repo ships
one domain (AMO); the per-path isolation is the seam for adding another.

    python -m mcp_server                 # serves every domain in DOMAINS (AMO)
    DOMAIN=AMO python -m mcp_server      # single-domain shorthand
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Config, load
from .graph import GraphClient
from .ratelimit import RateLimiter, RateLimitExceeded

log = logging.getLogger("amo.mcp")

_INSTRUCTIONS = """
This server exposes the {domain} catalog of "situation types" — judgment-territory
decisions where competent practitioners, given the same inputs, diverge into
different defensible choices rather than converging on one answer.

Start with list_situation_types() — each entry carries detectability (DIRECT /
DERIVED / ABSENT: whether any system already raises this) and which system
class detects it. get_strategies(situation_id) returns the competing responses,
each with its system_of_action (where it gets written, and how reversible that
write is) and delegation_ceiling (how far an agent could be trusted to take it
unsupervised). explain_qualifier(situation_id) returns solver_boundary — what
part of the situation is already solved and out of scope — alongside the
judgment/solver classification and rationale. match_situations(entity_id) takes
a concrete instance id (a work order, part, operation, purchase order line, …)
and returns which situation types it currently triggers. get_stack_model()
returns the
{domain} plant/system IT landscape itself — the systems, the interfaces between
them, the data objects each masters, and the known blind spots situation cards
are built against. get_situation_footprint(situation_id) traces one situation
across that landscape: detected in which system, evidenced by which, acted on
by which, covering which blind spot.

For an agent working a concrete instance: get_skill(situation_id) returns the
SKILL.md operating envelope for that situation (or the cross-cutting triage
skill for an empty id); read_commitments(id) returns the customer commitments a
situation or work order is exposed to; read_order_context(work_order_id)
returns everything the graph holds about one work order — fields, provenance,
required parts, operations, commitment, and which situations involve it.

Every response can carry the exact Cypher that ran underneath (include_cypher,
on by default) — that is the point, not a debug aid.
""".strip()


def build_domain_server(domain: str, graph: GraphClient, cfg: Config) -> MCPServer:
    limiter = RateLimiter(cfg.rate_limit_max, cfg.rate_limit_window)
    srv = MCPServer(
        f"{domain.lower()}-situation-bench",
        instructions=_INSTRUCTIONS.format(domain=domain),
        version="0.1.0",
    )

    def gate(ctx: Context | None) -> dict | None:
        key = "anon"
        try:
            if ctx is not None:
                h = ctx.headers or {}
                key = h.get("fly-client-ip") or h.get("x-forwarded-for", "anon").split(",")[0].strip()
        except Exception:  # noqa: BLE001 - never let limiter plumbing break a call
            pass
        try:
            limiter.check(key)
            return None
        except RateLimitExceeded as exc:
            return {"error": "rate_limited", "message": str(exc)}

    def with_cypher(payload: dict, cypher, include: bool) -> dict:
        if include:
            payload["cypher"] = cypher
        return payload

    @srv.tool(
        description=f"List every {domain} situation type in the catalog "
        "(id, name, trigger condition, judgment/solver classification)."
    )
    def list_situation_types(include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        rows, cypher = graph.list_situation_types()
        return with_cypher(
            {"domain": domain, "count": len(rows), "situation_types": rows},
            cypher,
            include_cypher,
        )

    @srv.tool(
        description="Given a concrete instance id (work order, part, operation, "
        f"purchase order line, …), return which {domain} situation types it "
        "currently triggers, with the matched instance ids."
    )
    def match_situations(entity_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        result, cyphers = graph.match_situations(entity_id.strip())
        return with_cypher(result, cyphers, include_cypher)

    @srv.tool(
        description="Return the competing, individually defensible strategies for "
        "a situation type — each with its preconditions, trade-off, system_of_action "
        "(where the write lands and how reversible it is), delegation_ceiling and "
        "any known_limitation (e.g. a trade-off that reads more history than the "
        "schema retains). Also returns the situation's solver_boundary."
    )
    def get_strategies(situation_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        sid = situation_id.strip()
        meta, rows, cyphers = graph.get_strategies(sid)
        if meta is None:
            payload: dict = {
                "situation_id": sid,
                "domain": domain,
                "strategies": [],
                "note": f"no situation {sid!r} in the {domain} catalog",
            }
        else:
            payload = {
                "situation_id": sid,
                "domain": domain,
                "solver_boundary": meta["solver_boundary"],
                "strategies": rows,
            }
        return with_cypher(payload, cyphers, include_cypher)

    @srv.tool(
        description="Explain why a situation type is judgment rather than solver: "
        "the classification, whether practitioners diverge, the rationale, "
        "solver_boundary — what part of the situation is already solved and out "
        "of scope for an agent — and, where the trigger reasons about time, its "
        "temporal_semantics (which axis each field reads) and tracked_transitions "
        "(a field carrying exactly one prior value plus the transaction time of "
        "the change)."
    )
    def explain_qualifier(situation_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        sid = situation_id.strip()
        row, cypher = graph.explain_qualifier(sid)
        payload: dict = {"situation_id": sid, "domain": domain}
        if row is None:
            payload["note"] = f"no situation {sid!r} in the {domain} catalog"
        else:
            payload.update(row)
        return with_cypher(payload, cypher, include_cypher)

    @srv.tool(
        description=f"Return the {domain} reference model — the plant/system IT "
        "landscape every situation card points at. `systems` (what each emits "
        "and accepts as writes, and its write_semantics), `interfaces` (which "
        "system sends which object to which, and how often), `known_blind_spots` "
        "(a system pair with no shared owner, and the card that covers it), plus "
        "`data_objects`, `business_processes`, `standards`, and `example_queries` "
        "— vetted Cypher the graph shape makes answerable."
    )
    def get_stack_model(include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        result, cypher = graph.get_stack_model()
        if result is None:
            payload = {"domain": domain, "note": f"no reference model loaded for {domain}"}
        else:
            payload = result
        return with_cypher(payload, cypher, include_cypher)

    @srv.tool(
        description="Which systems a situation type spans: the system it is "
        "detected in, the systems that hold the evidence to judge it, the "
        "systems its strategies act on, and the blind spot it covers. "
        "`cross_system_enforcement` is true when it is detected in one system "
        "and acted on in another — the cross-system scope this bench targets."
    )
    def get_situation_footprint(situation_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        sid = situation_id.strip()
        result, cypher = graph.get_situation_footprint(sid)
        if result is None:
            payload: dict = {
                "situation_id": sid,
                "domain": domain,
                "note": f"no situation {sid!r} in the {domain} catalog",
            }
        else:
            payload = {"domain": domain, **result}
        return with_cypher(payload, cypher, include_cypher)

    @srv.tool(
        description="Return the SKILL.md operating envelope for a situation type "
        "— how to recognise it from plain language, the fixed tool-call order, "
        "what a complete answer contains, and the local vocabulary. Pass a "
        "situation id (e.g. \"SIT-AMO-001\"), or \"triage\" / an empty string for "
        "the cross-cutting triage skill that gates every turn. The card, served "
        "by the other tools, remains the source of truth; the skill only restates "
        "strategy names for readability."
    )
    def get_skill(situation_id: str = "", include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        skill, cypher = graph.get_skill(situation_id)
        if skill is None:
            want = situation_id.strip() or "triage"
            payload: dict = {"domain": domain, "requested": want, "skill": None,
                             "note": f"no skill for {want!r} in the {domain} catalog"}
        else:
            payload = {"domain": domain, "skill": skill}
        return with_cypher(payload, cypher, include_cypher)

    @srv.tool(
        description="Given a situation-type id or a work-order id, return the "
        "customer commitments in scope — customer, contractual tier, commit and "
        "need dates, and whether the customer accepts a partial shipment. The "
        "input for naming which party absorbs a shortfall before strategies are "
        "presented; it surfaces the commitments, it does not choose."
    )
    def read_commitments(entity_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        result, cyphers = graph.read_commitments(entity_id)
        return with_cypher({"domain": domain, **result}, cyphers, include_cypher)

    @srv.tool(
        description="Everything the graph holds about one work order: its "
        "business fields and provenance (source system, valid time, transaction "
        "time), the parts it requires (with projected availability), its "
        "operations, the build and programme it sits in, its customer "
        "commitment, and which situation types involve it. The instance read a "
        "precondition check runs against — with no instance data, preconditions "
        "stay UNVERIFIED."
    )
    def read_order_context(work_order_id: str, include_cypher: bool = True, ctx: Context = None) -> dict:
        if (limited := gate(ctx)) is not None:
            return limited
        result, cyphers = graph.read_order_context(work_order_id)
        if result is None:
            payload: dict = {
                "domain": domain,
                "work_order_id": work_order_id.strip(),
                "note": f"no work order {work_order_id.strip()!r} in the {domain} catalog",
            }
        else:
            payload = {"domain": domain, **result}
        return with_cypher(payload, cyphers, include_cypher)

    return srv


def build_app(cfg: Config) -> tuple[Starlette, list[GraphClient]]:
    graphs: list[GraphClient] = []
    mounts: list[Mount] = []
    sub_apps = []

    if cfg.allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[*cfg.allowed_hosts, "127.0.0.1:*", "localhost:*"],
        )
    else:
        # Public server: the Host-header check (meant for browser-reachable
        # localhost servers) does not apply. Set MCP_ALLOWED_HOSTS to turn it on.
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    for domain in cfg.domains:
        graph = GraphClient(domain, cfg.memgraph_uri, cfg.memgraph_user, cfg.memgraph_password)
        graphs.append(graph)
        srv = build_domain_server(domain, graph, cfg)
        sub_app = srv.streamable_http_app(streamable_http_path="/mcp", transport_security=security)
        sub_apps.append(sub_app)
        mounts.append(Mount(cfg.mount_path(domain), app=sub_app))
        log.info("mounted %s at %s", domain, cfg.endpoint(domain))

    async def healthz(_request):
        status = {}
        ok = True
        for g in graphs:
            try:
                g.verify()
                status[g.domain] = "ok"
            except Exception as exc:  # noqa: BLE001
                status[g.domain] = f"error: {exc}"
                ok = False
        return JSONResponse(
            {"ok": ok, "domains": status, "endpoints": [cfg.endpoint(d) for d in cfg.domains]},
            status_code=200 if ok else 503,
        )

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:
            for sub in sub_apps:
                await stack.enter_async_context(sub.router.lifespan_context(_app))
            yield
        for g in graphs:
            g.close()

    app = Starlette(
        routes=[Route("/healthz", healthz), Route("/", healthz), *mounts],
        lifespan=lifespan,
    )
    return app, graphs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load()
    app, graphs = build_app(cfg)
    for g in graphs:
        try:
            g.verify()
            log.info("connected to Memgraph for %s at %s", g.domain, cfg.memgraph_uri)
        except Exception as exc:  # noqa: BLE001
            log.warning("Memgraph not reachable for %s (%s) — /healthz will report", g.domain, exc)
    log.info("serving domains %s on %s:%s", ",".join(cfg.domains), cfg.host, cfg.port)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
