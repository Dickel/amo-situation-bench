"""Memgraph connection + Cypher generation for the AMO situations graph.

Connection is Bolt, via the `neo4j` driver (Memgraph is Bolt-compatible).

The reference model (`MODEL-AMO-PLANT-IT`) loads as a graph:

    ReferenceModel --INCLUDES--> System / DataObject / BusinessProcess / Standard
    System --EXECUTES--> BusinessProcess
    System --MASTERS--> DataObject
    BusinessProcess --CONSUMES / PRODUCES--> DataObject
    System --SENDS--> Interface --TO--> System         (SENDS reified)
    Interface --CARRIES--> DataObject
    System --COMPLIES_WITH--> Standard
    ReferenceModel --HAS_BLIND_SPOT--> BlindSpot --INVOLVES_SYSTEM--> System
    ReferenceModel --DEMONSTRATES--> ExampleQuery

Loading a situation card also creates edges into that graph:

    SituationType --DETECTED_BY--> System        from trigger.source.system_class
    SituationType --EVIDENCED_BY--> System        from system_of_record.source_systems
    SituationType --COVERS--> BlindSpot           from known_blind_spots[].card
    Strategy --ACTS_ON--> System                  from system_of_action[].system_class
    Strategy --WRITES--> DataObject               strict-match from system_of_action[].writes

`system_of_action` is an `ActionPath` node (Memgraph properties can't hold
nested maps, and flattening it is unqueryable regardless).
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

from .cards import (
    ActionPath,
    BlindSpot,
    Card,
    Edge,
    Entity,
    ExampleQuery,
    ReferenceModelCard,
    Strategy,
    TrackedTransition,
)
from .skills import SkillDoc

DEFAULT_URI = "bolt://localhost:7687"

# SENDS is reified into an :Interface node (handled specially below). BETWEEN
# edges in the model's `edges:` list reference BlindSpot ids that `entity_refs`
# never declares — BlindSpots load from `known_blind_spots` instead, so BETWEEN
# is skipped here (a known source inconsistency, not a silent drop).
_STACK_EDGE_SKIP = {"SENDS", "BETWEEN"}


@contextmanager
def driver() -> Iterator[Any]:
    from neo4j import GraphDatabase

    uri = os.environ.get("MEMGRAPH_URI", DEFAULT_URI)
    user = os.environ.get("MEMGRAPH_USER")
    password = os.environ.get("MEMGRAPH_PASSWORD")
    auth = (user, password) if user is not None else ("", "")
    drv = GraphDatabase.driver(uri, auth=auth)
    try:
        drv.verify_connectivity()
        yield drv
    finally:
        drv.close()


Statement = tuple[str, dict]


def wipe() -> Statement:
    return "MATCH (n) DETACH DELETE n", {}


# ── situation cards: instance graph ─────────────────────────────────────────


def entity_statements(card: Card, *, with_sample: bool = True) -> list[Statement]:
    out: list[Statement] = []
    for ent in card.entities:
        props: dict[str, Any] = {"id": ent.id, "domain": card.domain}
        if with_sample:
            props.update(card.sample_instance.get(ent.id, {}))
        out.append(
            (
                f"MERGE (n:`{ent.label}` {{id: $id}}) SET n += $props, n.domain = $domain",
                {"id": ent.id, "domain": card.domain, "props": props},
            )
        )
    return out


def edge_statements(card: Card) -> list[Statement]:
    return [
        (
            f"MATCH (a {{id: $src}}), (b {{id: $dst}}) MERGE (a)-[:`{e.rel}`]->(b)",
            {"src": e.src, "dst": e.dst},
        )
        for e in card.edges
    ]


def card_only_statements(card: Card) -> list[Statement]:
    """Just enough to evaluate one card's trigger.pattern in isolation."""
    return entity_statements(card, with_sample=True) + edge_statements(card)


# ── situation cards: SituationType / Strategy / ActionPath ──────────────────


def situation_statements(card: Card) -> list[Statement]:
    out: list[Statement] = [_situation_type_stmt(card)]
    for tt_order, tt in enumerate(card.tracked_transitions):
        out.append(_tracked_transition_stmt(card, tt, tt_order))
    for order, strat in enumerate(card.strategies):
        out.append(_strategy_stmt(card, strat, order))
        for ap_order, ap in enumerate(strat.action_paths):
            out.append(_action_path_stmt(card, strat, ap, ap_order))
    for ent in card.entities:
        out.append(
            (
                "MATCH (s:SituationType {id: $sid}), (e {id: $eid}) MERGE (s)-[:INVOLVES]->(e)",
                {"sid": card.id, "eid": ent.id},
            )
        )
    out.append(
        (
            "MATCH (s:SituationType {id: $sid}), (m:ReferenceModel {id: $mid}) "
            "MERGE (s)-[:USES_STACK]->(m)",
            {"sid": card.id, "mid": card.stack_ref},
        )
    )
    return out


def _situation_type_stmt(card: Card) -> Statement:
    src = card.trigger_source
    return (
        """
        MERGE (s:SituationType {id: $id})
        SET s.domain = $domain,
            s.name = $name,
            s.stack_ref = $stack_ref,
            s.trigger_condition = $condition,
            s.trigger_pattern = $pattern,
            s.trigger_pattern_note = $pattern_note,
            s.trigger_source_system_class = $src_system_class,
            s.trigger_source_reference_vendor = $src_reference_vendor,
            s.trigger_source_emitting_object = $src_emitting_object,
            s.trigger_source_emission_mode = $src_emission_mode,
            s.trigger_source_latency_class = $src_latency_class,
            s.source_systems = $source_systems,
            s.detectability = $detectability,
            s.detectability_note = $detectability_note,
            s.solver_boundary = $solver_boundary,
            s.context_features = $context_features,
            s.temporal_semantics = $temporal_semantics,
            s.qualifier_divergence = $q_div,
            s.qualifier_rationale = $q_rat,
            s.qualifier_classification = $q_cls
        """,
        {
            "id": card.id,
            "domain": card.domain,
            "name": card.name,
            "stack_ref": card.stack_ref,
            "condition": card.trigger_condition,
            "pattern": card.trigger_pattern,
            "pattern_note": card.pattern_note,
            "src_system_class": src.system_class,
            "src_reference_vendor": src.reference_vendor,
            "src_emitting_object": src.emitting_object,
            "src_emission_mode": src.emission_mode,
            "src_latency_class": src.latency_class,
            "source_systems": card.source_systems,
            "detectability": card.detectability,
            "detectability_note": card.detectability_note,
            "solver_boundary": card.solver_boundary,
            "context_features": card.context_features,
            # Memgraph can't hold a nested map as a property — flatten to
            # "field=axis" strings (v0.5 §2.10 temporal_semantics).
            "temporal_semantics": [f"{k}={v}" for k, v in sorted(card.temporal_semantics.items())],
            "q_div": card.qualifier_divergence,
            "q_rat": card.qualifier_rationale,
            "q_cls": card.qualifier_classification,
        },
    )


def _strategy_stmt(card: Card, strat: Strategy, order: int) -> Statement:
    strat_id = f"{card.id}:{strat.id or order}"
    return (
        """
        MATCH (s:SituationType {id: $sid})
        MERGE (st:Strategy {id: $strat_id})
        SET st.domain = $domain,
            st.situation_id = $sid,
            st.local_id = $local_id,
            st.name = $name,
            st.doctrine = $doctrine,
            st.preconditions = $preconditions,
            st.trade_off = $trade_off,
            st.delegation_ceiling = $delegation_ceiling,
            st.known_limitation = $known_limitation,
            st.order = $order
        MERGE (s)-[:HAS_STRATEGY]->(st)
        """,
        {
            "sid": card.id,
            "strat_id": strat_id,
            "domain": card.domain,
            "local_id": strat.id,
            "name": strat.name,
            "doctrine": strat.doctrine,
            "preconditions": strat.preconditions,
            "trade_off": strat.trade_off,
            "delegation_ceiling": strat.delegation_ceiling,
            "known_limitation": strat.known_limitation,
            "order": order,
        },
    )


def _tracked_transition_stmt(card: Card, tt: TrackedTransition, order: int) -> Statement:
    """v0.5 §2.11 — `(:SituationType)-[:TRACKS_TRANSITION]->(:TrackedTransition)`.
    `retains` is fixed at 1 (parser-enforced); stored so the bound is visible in
    the graph, not just the source."""
    tt_id = f"{card.id}:transition:{order}"
    return (
        """
        MATCH (s:SituationType {id: $sid})
        MERGE (t:TrackedTransition {id: $tt_id})
        SET t.domain = $domain, t.node_type = $node_type, t.field = $field,
            t.retains = 1, t.note = $note
        MERGE (s)-[:TRACKS_TRANSITION]->(t)
        """,
        {
            "sid": card.id,
            "tt_id": tt_id,
            "domain": card.domain,
            "node_type": tt.node_type,
            "field": tt.field,
            "note": tt.note,
        },
    )


def _action_path_stmt(card: Card, strat: Strategy, ap: ActionPath, order: int) -> Statement:
    strat_id = f"{card.id}:{strat.id}"
    ap_id = f"{strat_id}:action:{order}"
    return (
        """
        MATCH (st:Strategy {id: $strat_id})
        MERGE (ap:ActionPath {id: $ap_id})
        SET ap.domain = $domain,
            ap.execution_path = $execution_path,
            ap.system_class = $system_class,
            ap.endpoint = $endpoint,
            ap.operation = $operation,
            ap.writes = $writes,
            ap.reversibility = $reversibility,
            ap.authority = $authority,
            ap.order = $order
        MERGE (st)-[:HAS_ACTION_PATH]->(ap)
        """,
        {
            "strat_id": strat_id,
            "ap_id": ap_id,
            "domain": card.domain,
            "execution_path": ap.execution_path,
            "system_class": ap.system_class,
            "endpoint": ap.endpoint,
            "operation": ap.operation,
            "writes": ap.writes,
            "reversibility": ap.reversibility,
            "authority": ap.authority,
            "order": order,
        },
    )


# ── reference-model cards ────────────────────────────────────────────────────


def reference_model_statements(model: ReferenceModelCard) -> list[Statement]:
    out: list[Statement] = [
        (
            "MERGE (m:ReferenceModel {id: $id}) "
            "SET m.domain = $domain, m.name = $name, m.purpose = $purpose, m.has_graph = $has_graph",
            {
                "id": model.id,
                "domain": model.domain,
                "name": model.name,
                "purpose": model.purpose,
                "has_graph": model.has_graph,
            },
        )
    ]
    out += _stack_graph_statements(model)
    for i, bs in enumerate(model.known_blind_spots):
        out += _blind_spot_stmts(model, bs, i)
    for i, eq in enumerate(model.example_queries):
        out.append(_example_query_stmt(model, eq, i))
    return out


# --- System / DataObject / BusinessProcess / Standard nodes ------------------


def _stack_graph_statements(model: ReferenceModelCard) -> list[Statement]:
    sysdef_by_class = {s.system_class: s for s in model.systems}
    out: list[Statement] = []

    for ent in model.entity_refs:
        out.append(_stack_node_stmt(model, ent, sysdef_by_class))

    iface_seq = 0
    for edge in model.stack_edges:
        if edge.rel == "SENDS":
            out += _sends_interface_stmts(model, edge, iface_seq)
            iface_seq += 1
        elif edge.rel in _STACK_EDGE_SKIP:
            continue
        else:
            out.append(
                (
                    f"MATCH (a {{id: $src}}), (b {{id: $dst}}) MERGE (a)-[:`{edge.rel}`]->(b)",
                    {"src": edge.src, "dst": edge.dst},
                )
            )
    return out


def _stack_node_stmt(model: ReferenceModelCard, ent: Entity, sysdef_by_class: dict) -> Statement:
    props: dict[str, Any] = {"id": ent.id, "domain": model.domain}
    props.update({k: v for k, v in ent.props.items() if v is not None})
    # Enrich :System nodes with the descriptive fields from the `systems:` table.
    if ent.label == "System":
        sd = sysdef_by_class.get(ent.props.get("system_class"))
        if sd is not None:
            props.update(
                role=sd.role,
                emits=sd.emits,
                accepts_writes=sd.accepts_writes,
                latency=sd.latency,
                key_identifiers=sd.key_identifiers,
            )
            if sd.note:
                props["note"] = sd.note
            if sd.default_write_semantics:  # v0.5 §2.12 — per-:System fallback
                props["default_write_semantics"] = sd.default_write_semantics
    return (
        f"MERGE (n:`{ent.label}` {{id: $id}}) SET n += $props "
        f"WITH n MATCH (m:ReferenceModel {{id: $mid}}) MERGE (m)-[:INCLUDES]->(n)",
        {"id": ent.id, "props": props, "mid": model.id},
    )


def _sends_interface_stmts(model: ReferenceModelCard, edge: Edge, seq: int) -> list[Statement]:
    iface_id = f"{model.id}:iface:{seq}"
    carries = edge.props.get("carries")
    cadence = edge.props.get("cadence")
    stmts: list[Statement] = [
        (
            """
            MATCH (src {id: $src}), (dst {id: $dst})
            MERGE (i:Interface {id: $iface_id})
            SET i.domain = $domain, i.cadence = $cadence,
                i.from_id = $src, i.to_id = $dst
            MERGE (src)-[:SENDS]->(i)
            MERGE (i)-[:TO]->(dst)
            """,
            {
                "iface_id": iface_id,
                "src": edge.src,
                "dst": edge.dst,
                "domain": model.domain,
                "cadence": cadence,
            },
        )
    ]
    if carries:
        stmts.append(
            (
                "MATCH (i:Interface {id: $iface_id}), (o {id: $carries}) MERGE (i)-[:CARRIES]->(o)",
                {"iface_id": iface_id, "carries": carries},
            )
        )
    return stmts


def _example_query_stmt(model: ReferenceModelCard, eq: ExampleQuery, index: int) -> Statement:
    eq_id = f"{model.id}:query:{index}"
    return (
        """
        MERGE (q:ExampleQuery {id: $eq_id})
        SET q.domain = $domain, q.name = $name, q.cypher = $cypher, q.note = $note
        WITH q MATCH (m:ReferenceModel {id: $mid})
        MERGE (m)-[:DEMONSTRATES]->(q)
        """,
        {
            "eq_id": eq_id,
            "mid": model.id,
            "domain": model.domain,
            "name": eq.name,
            "cypher": eq.cypher,
            "note": eq.note,
        },
    )


# --- blind spots ---------------------------------------------------------


def _blind_spot_stmts(model: ReferenceModelCard, bs: BlindSpot, index: int) -> list[Statement]:
    bs_id = f"{model.id}:blindspot:{index}"
    stmts: list[Statement] = [
        (
            """
            MERGE (b:BlindSpot {id: $bs_id})
            SET b.domain = $domain, b.gap = $gap
            WITH b MATCH (m:ReferenceModel {id: $mid})
            MERGE (m)-[:HAS_BLIND_SPOT]->(b)
            """,
            {"bs_id": bs_id, "mid": model.id, "domain": model.domain, "gap": bs.gap},
        )
    ]
    for system_class in bs.systems:
        stmts.append(
            (
                "MATCH (b:BlindSpot {id: $bs_id}), (sys {system_class: $sc, domain: $domain}) "
                "MERGE (b)-[:INVOLVES_SYSTEM]->(sys)",
                {"bs_id": bs_id, "sc": system_class, "domain": model.domain},
            )
        )
    return stmts


# ── situation → stack graph edges (has_graph domains only) ──────────────────


_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def situation_stack_edges(
    card: Card, model: ReferenceModelCard
) -> tuple[list[Statement], list[str]]:
    """DETECTED_BY / EVIDENCED_BY / ACTS_ON / WRITES / COVERS. Returns
    (statements, unresolved_writes) — every system_class is expected to resolve
    (the caller checks first), so unresolved_writes is the only soft miss."""
    d = card.domain
    out: list[Statement] = []

    out.append((
        "MATCH (s:SituationType {id: $sid}), (sys:System {system_class: $sc, domain: $domain}) "
        "MERGE (s)-[:DETECTED_BY]->(sys)",
        {"sid": card.id, "sc": card.trigger_source.system_class, "domain": d},
    ))
    for sc in dict.fromkeys(card.source_systems):
        out.append((
            "MATCH (s:SituationType {id: $sid}), (sys:System {system_class: $sc, domain: $domain}) "
            "MERGE (s)-[:EVIDENCED_BY]->(sys)",
            {"sid": card.id, "sc": sc, "domain": d},
        ))

    # DataObject normalised-name index for strict WRITES resolution.
    obj_norm = {
        e.id: "".join(_WORD_RE.findall(str(e.props.get("name", "")).lower()))
        for e in model.entity_refs
        if e.label == "DataObject"
    }
    unresolved: list[str] = []
    for order, strat in enumerate(card.strategies):
        strat_id = f"{card.id}:{strat.id or order}"
        for ap in strat.action_paths:
            out.append((
                "MATCH (st:Strategy {id: $sid}), (sys:System {system_class: $sc, domain: $domain}) "
                "MERGE (st)-[:ACTS_ON]->(sys)",
                {"sid": strat_id, "sc": ap.system_class, "domain": d},
            ))
            for w in ap.writes:
                obj_id = _match_write_to_object(w, obj_norm)
                if obj_id is None:
                    unresolved.append(f"{card.id}/{strat.id}: {w}")
                    continue
                out.append((
                    "MATCH (st:Strategy {id: $sid}), (o:DataObject {id: $oid}) "
                    "MERGE (st)-[:WRITES]->(o)",
                    {"sid": strat_id, "oid": obj_id},
                ))

    for i, bs in enumerate(model.known_blind_spots):
        if bs.card_id == card.id:
            out.append((
                "MATCH (s:SituationType {id: $sid}), (b:BlindSpot {id: $bs_id}) "
                "MERGE (s)-[:COVERS]->(b)",
                {"sid": card.id, "bs_id": f"{model.id}:blindspot:{i}"},
            ))
    return out, unresolved


def _match_write_to_object(write: str, obj_norm: dict[str, str]) -> str | None:
    """Strict, exact match only. `writes` is field-level
    (`reservation.work_order_id`, `dispatch_priority`, `planned_start_date`) and
    the DataObject names are object-level; the two vocabularies were authored
    independently, so most writes have no object-level target and fuzzy matching
    produces false edges (`planned_start_date` is not a "Supplier promise
    date"). A WRITES edge is created only when the write's leading segment,
    normalised, equals a DataObject name normalised — currently just
    `purchase_order` -> "Purchase order". Everything else stays as an
    ActionPath.writes property with no edge. Flagged as a spec gap, not forced."""
    head = "".join(_WORD_RE.findall(write.split(".", 1)[0].lower()))
    for oid, norm_name in obj_norm.items():
        if head and head == norm_name:
            return oid
    return None


# ── skills ───────────────────────────────────────────────────────────────────


def skill_statements(skill: SkillDoc) -> list[Statement]:
    """`(:Skill {name})` carrying the SKILL.md body, linked to its situation
    type by `HAS_SKILL` (the cross-cutting triage skill has no such link).
    Skills are versioned in Git; this copy exists only so `get_skill` is a
    graph read like every other tool — the container image never ships the
    `skills/` tree."""
    stmts: list[Statement] = [
        (
            """
            MERGE (k:Skill {name: $name})
            SET k.domain = $domain,
                k.classification = $classification,
                k.situation_id = $situation_id,
                k.detectability = $detectability,
                k.description = $description,
                k.allowed_tools = $allowed_tools,
                k.body = $body,
                k.is_triage = $is_triage
            """,
            {
                "name": skill.name,
                "domain": skill.domain,
                "classification": skill.classification,
                "situation_id": skill.situation_id,
                "detectability": skill.detectability,
                "description": skill.description,
                "allowed_tools": skill.allowed_tools,
                "body": skill.body,
                "is_triage": skill.is_triage,
            },
        )
    ]
    if skill.situation_id:
        stmts.append(
            (
                "MATCH (s:SituationType {id: $sid, domain: $domain}), (k:Skill {name: $name}) "
                "MERGE (s)-[:HAS_SKILL]->(k)",
                {"sid": skill.situation_id, "domain": skill.domain, "name": skill.name},
            )
        )
    return stmts


# ── full load ─────────────────────────────────────────────────────────────────


def full_load_statements(
    situations: list[Card],
    reference_models: list[ReferenceModelCard],
    skills: list[SkillDoc] | None = None,
) -> tuple[list[Statement], list[str]]:
    """Every statement needed to seed the graph, in order: the reference model
    first, then situation instance graphs, then SituationType/Strategy/ActionPath,
    then the situation→stack edges (which need both sides to exist), then skills
    (which need their SituationType). Returns (statements, unresolved_writes)."""
    models_by_id = {m.id: m for m in reference_models}
    stmts: list[Statement] = []
    unresolved: list[str] = []

    for model in reference_models:
        stmts += reference_model_statements(model)
    for card in situations:
        stmts += entity_statements(card, with_sample=True)
    for card in situations:
        stmts += edge_statements(card)
    for card in situations:
        stmts += situation_statements(card)
    for card in situations:
        model = models_by_id.get(card.stack_ref)
        if model is not None and model.has_graph:
            edges, misses = situation_stack_edges(card, model)
            stmts += edges
            unresolved += misses
    for skill in skills or []:
        stmts += skill_statements(skill)
    return stmts, unresolved
