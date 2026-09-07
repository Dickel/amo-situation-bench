"""The read-only graph layer.

Every method binds `domain` from config — never from a tool argument — so a
process serving one domain structurally cannot return another's data even if a
caller passes an id from it. `match_situations` additionally passes `domain` as
a query *parameter* when it runs a stored `trigger.pattern`, because patterns
reference `{domain: $domain}` inline on every node — without it every pattern
would fail outright.

The reference model is a graph: `:System` / `:DataObject` / `:BusinessProcess` /
`:Standard` nodes, `:Interface` reified from SENDS, and `DETECTED_BY` /
`EVIDENCED_BY` / `ACTS_ON` / `COVERS` edges from the situation cards.

Each method returns `(result, cypher)` where `cypher` is the exact query text
that ran. Surfacing it is a feature, not a debug aid.

Tools never write, and no method accepts free Cypher from a caller. The one
place stored query text is executed is `match_situations`, running the
loader-written `trigger_pattern` strings — vetted data, not caller input —
scoped to this process's domain.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

LIST_SITUATION_TYPES = """
MATCH (s:SituationType {domain: $domain})
RETURN s.id AS id,
       s.name AS name,
       s.trigger_condition AS trigger_condition,
       s.qualifier_classification AS classification,
       s.trigger_source_system_class AS detected_by_system_class,
       s.detectability AS detectability
ORDER BY s.id
""".strip()

FIND_ENTITY = """
MATCH (n {id: $entity_id, domain: $domain})
RETURN n.id AS id, labels(n) AS labels
""".strip()

SITUATION_TRIGGERS = """
MATCH (s:SituationType {domain: $domain})
WHERE s.trigger_pattern IS NOT NULL
RETURN s.id AS id, s.name AS name, s.trigger_pattern AS pattern
ORDER BY s.id
""".strip()

SITUATION_META = """
MATCH (s:SituationType {id: $situation_id, domain: $domain})
OPTIONAL MATCH (s)-[:TRACKS_TRANSITION]->(t:TrackedTransition)
WITH s, collect({node_type: t.node_type, field: t.field, retains: t.retains, note: t.note}) AS tt
RETURN s.name AS name,
       s.trigger_condition AS trigger_condition,
       s.trigger_source_system_class AS trigger_source_system_class,
       s.detectability AS detectability,
       s.detectability_note AS detectability_note,
       s.solver_boundary AS solver_boundary,
       s.temporal_semantics AS temporal_semantics,
       [x IN tt WHERE x.field IS NOT NULL] AS tracked_transitions,
       s.qualifier_classification AS classification,
       s.qualifier_divergence AS practitioner_divergence,
       s.qualifier_rationale AS rationale
""".strip()

GET_STRATEGIES = """
MATCH (s:SituationType {id: $situation_id, domain: $domain})-[:HAS_STRATEGY]->(st:Strategy)
MATCH (st)-[:HAS_ACTION_PATH]->(ap:ActionPath)
WITH st, collect({
    order: ap.order, execution_path: ap.execution_path, system_class: ap.system_class,
    endpoint: ap.endpoint, operation: ap.operation, writes: ap.writes,
    reversibility: ap.reversibility, authority: ap.authority
}) AS action_paths
RETURN st.local_id AS id, st.name AS name, st.doctrine AS doctrine,
       st.preconditions AS preconditions, st.trade_off AS trade_off,
       st.delegation_ceiling AS delegation_ceiling, st.known_limitation AS known_limitation,
       st.order AS order, action_paths
ORDER BY st.order
""".strip()

SITUATION_FOOTPRINT = """
MATCH (s:SituationType {id: $situation_id, domain: $domain})
OPTIONAL MATCH (s)-[:DETECTED_BY]->(d:System)
OPTIONAL MATCH (s)-[:EVIDENCED_BY]->(e:System)
OPTIONAL MATCH (s)-[:HAS_STRATEGY]->(st:Strategy)-[:ACTS_ON]->(a:System)
OPTIONAL MATCH (s)-[:COVERS]->(b:BlindSpot)
RETURN d.system_class AS detected_by,
       collect(DISTINCT e.system_class) AS evidence_systems,
       collect(DISTINCT a.system_class) AS acts_on_systems,
       collect(DISTINCT b.gap) AS covers_blind_spots
""".strip()

# ── reference-model queries ────────────────────────────────────────────────

MODEL_META = """
MATCH (m:ReferenceModel {domain: $domain})
RETURN m.id AS id, m.name AS name, m.purpose AS purpose, coalesce(m.has_graph, false) AS has_graph
""".strip()

STACK_SYSTEMS = """
MATCH (m:ReferenceModel {domain: $domain})-[:INCLUDES]->(sys:System)
RETURN sys.system_class AS system_class, sys.isa95_level AS isa95_level, sys.role AS role,
       sys.emits AS emits, sys.accepts_writes AS accepts_writes, sys.latency AS latency,
       sys.key_identifiers AS key_identifiers, sys.default_write_semantics AS default_write_semantics,
       sys.note AS note
ORDER BY sys.system_class
""".strip()

STACK_INTERFACES = """
MATCH (m:ReferenceModel {domain: $domain})-[:INCLUDES]->(a:System)-[:SENDS]->(i:Interface)-[:TO]->(b:System)
OPTIONAL MATCH (i)-[:CARRIES]->(o:DataObject)
RETURN a.system_class AS from, b.system_class AS to, o.name AS carries, i.cadence AS cadence
ORDER BY from, to
""".strip()

STACK_DATA_OBJECTS = """
MATCH (m:ReferenceModel {domain: $domain})-[:INCLUDES]->(o:DataObject)
OPTIONAL MATCH (sys:System)-[:MASTERS]->(o)
RETURN o.name AS name, o.write_semantics AS write_semantics,
       coalesce(o.tracked, false) AS tracked,
       collect(DISTINCT sys.system_class) AS mastered_by
ORDER BY name
""".strip()

STACK_BUSINESS_PROCESSES = """
MATCH (m:ReferenceModel {domain: $domain})-[:INCLUDES]->(bp:BusinessProcess)
OPTIONAL MATCH (sys:System)-[:EXECUTES]->(bp)
RETURN bp.name AS name, collect(DISTINCT sys.system_class) AS executed_by
ORDER BY name
""".strip()

STACK_STANDARDS = """
MATCH (m:ReferenceModel {domain: $domain})-[:INCLUDES]->(std:Standard)
OPTIONAL MATCH (sys:System)-[:COMPLIES_WITH]->(std)
RETURN std.name AS name, collect(DISTINCT sys.system_class) AS systems
ORDER BY name
""".strip()

STACK_BLIND_SPOTS = """
MATCH (m:ReferenceModel {domain: $domain})-[:HAS_BLIND_SPOT]->(bs:BlindSpot)
OPTIONAL MATCH (bs)-[:INVOLVES_SYSTEM]->(sys)
OPTIONAL MATCH (sit:SituationType)-[:COVERS]->(bs)
WITH bs, collect(DISTINCT sys.system_class) AS systems, collect(DISTINCT sit.id) AS covered_by
RETURN bs.gap AS gap, systems, covered_by
""".strip()

STACK_EXAMPLE_QUERIES = """
MATCH (m:ReferenceModel {domain: $domain})-[:DEMONSTRATES]->(q:ExampleQuery)
RETURN q.name AS name, q.cypher AS cypher, q.note AS note
ORDER BY q.name
""".strip()

# ── agent-support tools ────────────────────────────

GET_SKILL_BY_SITUATION = """
MATCH (s:SituationType {id: $situation_id, domain: $domain})-[:HAS_SKILL]->(k:Skill)
RETURN k.name AS name, k.classification AS classification, k.situation_id AS situation_id,
       k.detectability AS detectability, k.description AS description,
       k.allowed_tools AS allowed_tools, k.body AS body
""".strip()

GET_TRIAGE_SKILL = """
MATCH (k:Skill {domain: $domain, is_triage: true})
RETURN k.name AS name, k.classification AS classification, k.situation_id AS situation_id,
       k.detectability AS detectability, k.description AS description,
       k.allowed_tools AS allowed_tools, k.body AS body
""".strip()

LIST_SKILLS = """
MATCH (k:Skill {domain: $domain})
RETURN k.name AS name, k.situation_id AS situation_id, k.classification AS classification,
       k.description AS description
ORDER BY k.is_triage DESC, k.name
""".strip()

# read_commitments — the customer commitments a situation (or a work order)
# is exposed to. AG-02 (Stake Resolver) uses this to name the absorbing party
# before AG-04 presents. Accepts a SituationType id or an instance id.
READ_COMMITMENTS = """
MATCH (anchor {id: $id, domain: $domain})
OPTIONAL MATCH (anchor:SituationType)-[:INVOLVES]->(w1:WorkOrder {domain: $domain})
WITH anchor, collect(DISTINCT w1) AS via_situation
WITH anchor,
     CASE WHEN anchor:WorkOrder THEN [anchor] ELSE via_situation END AS wos
UNWIND wos AS w
MATCH (w)-[:COMMITTED_TO]->(c:Customer {domain: $domain})
RETURN w.id AS work_order,
       w.status AS work_order_status,
       w.customer_tier AS customer_tier,
       w.commit_date AS commit_date,
       w.need_date AS need_date,
       c.id AS customer,
       c.accepts_partial_shipment AS accepts_partial_shipment,
       c.source_system_class AS customer_source_system
ORDER BY work_order, customer
""".strip()

# read_order_context — everything the graph holds about one work order:
# business fields + provenance, part requirements, operations, the build/program
# it sits in, its commitment, and which situations involve it. AG-02 / AG-03.
READ_ORDER_CONTEXT_WO = """
MATCH (w:WorkOrder {id: $id, domain: $domain})
RETURN properties(w) AS work_order
""".strip()

READ_ORDER_CONTEXT_NEIGHBOURS = """
MATCH (w:WorkOrder {id: $id, domain: $domain})
OPTIONAL MATCH (w)-[:REQUIRES]->(p:Part {domain: $domain})
OPTIONAL MATCH (w)-[:HAS_OPERATION]->(op:Operation {domain: $domain})
OPTIONAL MATCH (w)-[:COMMITTED_TO]->(c:Customer {domain: $domain})
OPTIONAL MATCH (b:Build {domain: $domain})-[:CONTAINS]->(w)
OPTIONAL MATCH (prog:Program {domain: $domain})-[:CONTAINS]->(b)
OPTIONAL MATCH (s:SituationType {domain: $domain})-[:INVOLVES]->(w)
RETURN collect(DISTINCT properties(p))  AS parts,
       collect(DISTINCT properties(op)) AS operations,
       collect(DISTINCT properties(c))  AS commitments,
       collect(DISTINCT b.id)           AS builds,
       collect(DISTINCT prog.id)        AS programs,
       collect(DISTINCT s.id)           AS in_situations
""".strip()


class GraphClient:
    """Read-only access to one domain's slice of the graph."""

    def __init__(self, domain: str, uri: str, user: str | None = None, password: str | None = None):
        self.domain = domain
        from neo4j import GraphDatabase

        auth = (user, password) if user is not None else ("", "")
        self._driver = GraphDatabase.driver(uri, auth=auth)

    def close(self) -> None:
        self._driver.close()

    def verify(self) -> None:
        self._driver.verify_connectivity()

    @contextmanager
    def _session(self) -> Iterator[Any]:
        with self._driver.session() as session:
            yield session

    # ── situation tools ─────────────────────────────────────────────────────

    def list_situation_types(self) -> tuple[list[dict], str]:
        with self._session() as s:
            rows = [dict(r) for r in s.run(LIST_SITUATION_TYPES, domain=self.domain)]
        return rows, LIST_SITUATION_TYPES

    def get_strategies(self, situation_id: str) -> tuple[dict | None, list[dict], list[str]]:
        with self._session() as s:
            meta = s.run(SITUATION_META, situation_id=situation_id, domain=self.domain).single()
            if meta is None:
                return None, [], [SITUATION_META]
            rows = [dict(r) for r in s.run(GET_STRATEGIES, situation_id=situation_id, domain=self.domain)]
        for r in rows:
            r["action_paths"] = [
                {k: v for k, v in ap.items() if k != "order"}
                for ap in sorted(r.pop("action_paths"), key=lambda a: a["order"])
            ]
            r.pop("order", None)
        return dict(meta), rows, [SITUATION_META, GET_STRATEGIES]

    def explain_qualifier(self, situation_id: str) -> tuple[dict | None, str]:
        with self._session() as s:
            rec = s.run(SITUATION_META, situation_id=situation_id, domain=self.domain).single()
        return (dict(rec) if rec else None), SITUATION_META

    def get_situation_footprint(self, situation_id: str) -> tuple[dict | None, str]:
        """Which systems a situation spans: detected in / evidenced by / acted
        on / blind spot covered."""
        with self._session() as s:
            meta = s.run(SITUATION_META, situation_id=situation_id, domain=self.domain).single()
            if meta is None:
                return None, SITUATION_FOOTPRINT
            fp = s.run(SITUATION_FOOTPRINT, situation_id=situation_id, domain=self.domain).single()
        result = {
            "situation_id": situation_id,
            "detected_by": fp["detected_by"],
            "evidence_systems": sorted(x for x in fp["evidence_systems"] if x),
            "acts_on_systems": sorted(x for x in fp["acts_on_systems"] if x),
            "covers_blind_spots": [g for g in fp["covers_blind_spots"] if g],
        }
        acts = set(result["acts_on_systems"])
        result["cross_system_enforcement"] = bool(
            result["detected_by"] and acts and acts != {result["detected_by"]}
        )
        return result, SITUATION_FOOTPRINT

    def match_situations(self, entity_id: str) -> tuple[dict, list[str]]:
        cyphers: list[str] = [FIND_ENTITY, SITUATION_TRIGGERS]
        with self._session() as s:
            entity = s.run(FIND_ENTITY, entity_id=entity_id, domain=self.domain).single()
            if entity is None:
                return (
                    {
                        "entity_id": entity_id,
                        "found": False,
                        "note": f"no entity {entity_id!r} in the {self.domain} catalog",
                        "matches": [],
                    },
                    cyphers,
                )
            triggers = [dict(r) for r in s.run(SITUATION_TRIGGERS, domain=self.domain)]
            matches: list[dict] = []
            for trig in triggers:
                pattern = trig["pattern"]
                cyphers.append(pattern)
                try:
                    records = list(s.run(pattern, domain=self.domain))
                except Exception as exc:  # noqa: BLE001 - report, don't crash the tool
                    matches.append({"situation_id": trig["id"], "error": _one_line(exc)})
                    continue
                hit_instances = [
                    ids for rec in records if entity_id in (ids := _ids_in_record(rec))
                ]
                if hit_instances:
                    matches.append(
                        {
                            "situation_id": trig["id"],
                            "name": trig["name"],
                            "matched_instances": sorted({i for ids in hit_instances for i in ids}),
                        }
                    )
        return (
            {
                "entity_id": entity_id,
                "found": True,
                "labels": list(entity["labels"]),
                "matches": matches,
            },
            cyphers,
        )

    # ── reference-model tool ────────────────────────────────────────────────

    def get_stack_model(self) -> tuple[dict | None, str]:
        # All 8 sub-queries run in ONE read transaction, so
        # the assembled model is a single consistent snapshot — it can never be
        # half old / half new because a `loader.load` commit landed mid-call.
        with self._driver.session() as session:
            return session.execute_read(self._stack_model_tx, self.domain)

    @staticmethod
    def _stack_model_tx(tx: Any, domain: str) -> tuple[dict | None, str]:
        meta = tx.run(MODEL_META, domain=domain).single()
        if meta is None:
            return None, MODEL_META
        has_graph = bool(meta["has_graph"])
        systems = [dict(r) for r in tx.run(STACK_SYSTEMS, domain=domain)]
        # Coherence guard: a graph-backed model always resolves to >= 1 :System
        # node. Zero systems with has_graph=true means the graph is mid-reload
        # or the load did not finish — return an explicit error rather than a
        # plausible-looking empty stack a caller would read as "no systems".
        if _stack_is_incoherent(has_graph, systems):
            return {
                "id": meta["id"],
                "name": meta["name"],
                "purpose": meta["purpose"],
                "has_graph": True,
                "error": "stack_model_incomplete",
                "note": (
                    "the reference model resolved to zero :System nodes despite "
                    "has_graph=true — the graph is mid-reload or the last load did not "
                    "complete. Retry the call; if it persists, re-run `loader.load`."
                ),
                "systems": [],
                "interfaces": [],
                "known_blind_spots": [],
            }, "\n".join([MODEL_META, STACK_SYSTEMS])
        result = {
            "id": meta["id"],
            "name": meta["name"],
            "purpose": meta["purpose"],
            "has_graph": has_graph,
            "systems": systems,
            "interfaces": [dict(r) for r in tx.run(STACK_INTERFACES, domain=domain)],
            "known_blind_spots": [dict(r) for r in tx.run(STACK_BLIND_SPOTS, domain=domain)],
            "data_objects": [dict(r) for r in tx.run(STACK_DATA_OBJECTS, domain=domain)],
            "business_processes": [dict(r) for r in tx.run(STACK_BUSINESS_PROCESSES, domain=domain)],
            "standards": [dict(r) for r in tx.run(STACK_STANDARDS, domain=domain)],
            "example_queries": [dict(r) for r in tx.run(STACK_EXAMPLE_QUERIES, domain=domain)],
        }
        cyphers = [
            MODEL_META, STACK_SYSTEMS, STACK_INTERFACES, STACK_BLIND_SPOTS,
            STACK_DATA_OBJECTS, STACK_BUSINESS_PROCESSES, STACK_STANDARDS, STACK_EXAMPLE_QUERIES,
        ]
        return result, "\n".join(cyphers)

    # ── agent-support tools ─────────────────────────

    def get_skill(self, situation_id: str) -> tuple[dict | None, str]:
        """The SKILL.md operating envelope for a situation type, or — for the
        literal `"triage"` / an empty id — the cross-cutting triage skill.
        Returns None when the domain has no matching skill loaded."""
        want = situation_id.strip()
        triage = want == "" or want.lower() in {"triage", f"{self.domain.lower()}-situation-triage"}
        cypher = GET_TRIAGE_SKILL if triage else GET_SKILL_BY_SITUATION
        params = {"domain": self.domain} if triage else {"situation_id": want, "domain": self.domain}
        with self._session() as s:
            rec = s.run(cypher, **params).single()
        if rec is None:
            return None, cypher
        return _native(dict(rec)), cypher

    def list_skills(self) -> tuple[list[dict], str]:
        with self._session() as s:
            rows = [_native(dict(r)) for r in s.run(LIST_SKILLS, domain=self.domain)]
        return rows, LIST_SKILLS

    def read_commitments(self, entity_id: str) -> tuple[dict, list[str]]:
        eid = entity_id.strip()
        with self._session() as s:
            anchor = s.run(FIND_ENTITY, entity_id=eid, domain=self.domain).single()
            rows = [_native(dict(r)) for r in s.run(READ_COMMITMENTS, id=eid, domain=self.domain)]
        result: dict[str, Any] = {"id": eid, "found": anchor is not None, "commitments": rows}
        if anchor is not None:
            result["labels"] = list(anchor["labels"])
        if anchor is None:
            result["note"] = f"no entity {eid!r} in the {self.domain} catalog"
        elif not rows:
            result["note"] = "entity resolved but no COMMITTED_TO customer in scope"
        return result, [FIND_ENTITY, READ_COMMITMENTS]

    def read_order_context(self, work_order_id: str) -> tuple[dict | None, list[str]]:
        wid = work_order_id.strip()
        cyphers = [READ_ORDER_CONTEXT_WO, READ_ORDER_CONTEXT_NEIGHBOURS]
        with self._session() as s:
            wo = s.run(READ_ORDER_CONTEXT_WO, id=wid, domain=self.domain).single()
            if wo is None:
                return None, cyphers
            nb = s.run(READ_ORDER_CONTEXT_NEIGHBOURS, id=wid, domain=self.domain).single()
        return _native({
            "work_order": dict(wo["work_order"]),
            "parts": [p for p in nb["parts"] if p],
            "operations": [o for o in nb["operations"] if o],
            "commitments": [c for c in nb["commitments"] if c],
            "builds": [b for b in nb["builds"] if b],
            "programs": [p for p in nb["programs"] if p],
            "in_situations": sorted(x for x in nb["in_situations"] if x),
        }), cyphers


def _stack_is_incoherent(has_graph: bool, systems: list) -> bool:
    """A graph-backed reference model that resolves to zero `:System` nodes is
    not a real state — the graph is mid-reload or the load did not finish.
    `get_stack_model` returns an explicit error for this rather than a
    plausible-looking empty stack."""
    return bool(has_graph) and not systems


def _native(value: Any) -> Any:
    """Recursively convert neo4j temporal / spatial types to JSON-native values.
    The v0.5 provenance properties are `datetime` / `date`; the MCP layer
    serialises tool results to JSON text, which cannot encode them raw."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_native(v) for v in value]
    return value


def _ids_in_record(record: Any) -> set[str]:
    found: set[str] = set()
    for value in record.values():
        _collect_ids(value, found)
    return found


def _collect_ids(value: Any, out: set[str]) -> None:
    if hasattr(value, "get") and not isinstance(value, dict):
        nid = value.get("id")
        if isinstance(nid, str):
            out.add(nid)
        return
    if isinstance(value, dict):
        nid = value.get("id")
        if isinstance(nid, str):
            out.add(nid)
        for v in value.values():
            _collect_ids(v, out)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            _collect_ids(v, out)


def _one_line(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]
