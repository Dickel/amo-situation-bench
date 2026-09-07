"""Parse the AMO situations markdown into structured cards — v0.5 schema.

Pure Python — no database. `parse_file()` is the entry point.

Two card types share the file: `card_type: situation` (`SIT-AMO-###`) and
`card_type: reference_model` (`MODEL-AMO-PLANT-IT`, the plant IT landscape a
situation card's `stack_ref` points at). Blocks are classified by their own
`id` + `card_type`, not by heading position — the reference-model card sits
under a bare `## 3.` heading with no id in the heading text.

The reference model is a graph: it carries its own `entity_refs` / `edges`
(System / DataObject / BusinessProcess / Standard nodes and typed edges) in
the same shape the situation cards use. `system_class` on a situation card is a
*reference* into that graph — an unresolvable value is a load error.

v0.5 adds provenance / bitemporality to instance state (§2.10-2.12):

  * ``tracked_transitions`` on a situation card — a field declared to carry
    ``<field>`` / ``<field>_prior`` / ``<field>_changed_at`` on its node.
    ``retains`` MUST equal 1; anything higher is a revision chain under
    another name and is rejected here (§2.11 / the parser check).
  * ``temporal_semantics`` — which axis (``source_valid_from`` vs
    ``graph_updated_at``) each time field on the card reads. Captured raw.
  * ``write_semantics`` (``APPEND_ONLY`` | ``UPDATABLE``) on every
    ``:DataObject`` entity_ref of a graph-backed reference model, with
    ``default_write_semantics`` as a per-``:System`` fallback (§2.12, §3).
  * Provenance properties (``source_*`` / ``graph_*`` / ``extraction_run_id``)
    ride through ``sample_instance`` as ordinary scalars — no parser change,
    but ``load.check_provenance_assertions`` enforces the load-time assertions.

A situation card carries `trigger.source`, `detectability`, `solver_boundary`,
and per-strategy `system_of_action` + `delegation_ceiling`. A block whose id
doesn't match a real card id (the schema-template blocks in section 2) is
silently skipped.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SITUATION_ID_RE = re.compile(r"^SIT-AMO-\d{3,}$")
MODEL_ID_RE = re.compile(r"^MODEL-AMO-[A-Z0-9_-]+$")
_YAML_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)
_REL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
# A node pattern with a label: `(var:Label` or `(var:Label {...}`. Captures the
# brace group (or None if the node has no properties at all) so callers can
# check every fresh node binding carries `{domain: $domain}` — see
# _require_domain_scoped_pattern.
_NODE_WITH_LABEL_RE = re.compile(r"\(\s*[A-Za-z_]\w*\s*:\s*[A-Za-z_][A-Za-z0-9_]*\s*(\{[^}]*\})?")

VALID_DOMAINS = {"AMO"}
VALID_CLASSIFICATIONS = {"judgment", "solver"}
VALID_DETECTABILITY = {"DIRECT", "DERIVED", "ABSENT"}
VALID_WRITE_SEMANTICS = {"APPEND_ONLY", "UPDATABLE"}

# v0.5 §2.10.2 — which instance node classes are *extracted* (versioned in the
# graph, carry provenance) versus *authored* (versioned in Git, carry none).
# `check_provenance_assertions` uses this to decide which sample_instance nodes
# the load-time assertions apply to. `Confirmation` is extracted but its DataObject is
# APPEND_ONLY, so its `source_valid_to` must stay null (handled via the
# reference model's write_semantics, not hard-coded here).
EXTRACTED_NODE_LABELS = {
    # §2.10.2 names these explicitly; the rest are instance classes that also
    # resolve from a source system (the v0.5 table is not exhaustive).
    "WorkOrder", "PurchaseOrder", "POLine", "Part", "Supplier", "Operation",
    "Reservation", "ProductFamily", "Commitment", "Confirmation",
    "EngineeringChange", "WorkCentre", "Sequence", "Customer", "Program", "Build",
}
PROVENANCE_KEYS = {
    "source_system_class", "source_system_instance", "source_id", "source_context",
    "source_valid_from", "source_valid_to", "source_recorded_at", "source_actor",
    "graph_ingested_at", "graph_updated_at", "graph_path_updated_at", "extraction_run_id",
}


class CardParseError(ValueError):
    """A card block is present but malformed."""


@dataclass(frozen=True)
class Entity:
    id: str
    label: str
    # Extra inline fields beyond id/type — only reference-model entity_refs
    # carry these (e.g. system_class, isa95_level, name). Empty for situation
    # cards, whose entity_refs are always bare {id, type}.
    props: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    # Extra inline fields beyond from/relationship/to — only reference-model
    # SENDS edges carry these (carries, cadence). Empty otherwise.
    props: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class TriggerSource:
    """DETECTION — where the signal that fires this situation comes from."""

    system_class: str
    emission_mode: str
    latency_class: str
    reference_vendor: str | None = None
    emitting_object: str | None = None


@dataclass(frozen=True)
class ActionPath:
    """ACTION — one write path a strategy uses. A strategy can have several."""

    execution_path: str
    system_class: str
    operation: str
    writes: list[str]
    reversibility: str
    authority: str
    endpoint: str | None = None


@dataclass(frozen=True)
class TrackedTransition:
    """v0.5 §2.11 — a situation-card declaration that a field on an instance
    node carries its immediately-preceding value (`<field>_prior`) and the
    transaction time of the change (`<field>_changed_at`). `retains` is fixed
    at 1 by construction (enforced in the parser); anything higher would be a
    revision chain."""

    node_type: str
    field: str
    note: str | None = None


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    doctrine: str
    preconditions: list[str]
    trade_off: str
    action_paths: list[ActionPath]
    delegation_ceiling: str
    known_limitation: str | None = None


@dataclass
class Card:
    """A situation card (`card_type: situation`)."""

    id: str
    domain: str
    name: str
    stack_ref: str
    source_systems: list[str]
    object_path: str
    entities: list[Entity]
    edges: list[Edge]
    trigger_source: TriggerSource
    detectability: str
    trigger_condition: str
    trigger_pattern: str
    solver_boundary: str
    context_features: list[str]
    sample_instance: dict[str, dict[str, Any]]
    strategies: list[Strategy]
    qualifier_divergence: str
    qualifier_rationale: str
    qualifier_classification: str
    pattern_note: str | None = None
    detectability_note: str | None = None
    tracked_transitions: list[TrackedTransition] = field(default_factory=list)
    temporal_semantics: dict[str, Any] = field(default_factory=dict, repr=False)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def entity_ids(self) -> set[str]:
        return {e.id for e in self.entities}

    @property
    def is_judgment(self) -> bool:
        return self.qualifier_classification == "judgment"


@dataclass(frozen=True)
class SystemDef:
    system_class: str
    isa95_level: str
    role: str
    emits: list[str]
    accepts_writes: list[str]
    latency: str
    key_identifiers: list[str]
    note: str | None = None
    # v0.5 §2.12 — fallback write_semantics for :DataObject nodes this system
    # MASTERS that do not declare their own. `None` where the system masters
    # nothing (HUMAN_ROUTINE) or the model has not declared it.
    default_write_semantics: str | None = None


@dataclass(frozen=True)
class Interface:
    src: str
    dst: str
    carries: str
    cadence: str
    note: str | None = None


@dataclass(frozen=True)
class BlindSpot:
    systems: list[str]
    gap: str
    card_id: str | None


@dataclass(frozen=True)
class ExampleQuery:
    """A curated, vetted Cypher example from `queries_this_enables` — surfaced
    to callers as documentation, never executed by the loader or MCP server."""

    name: str
    cypher: str
    note: str | None = None


@dataclass
class ReferenceModelCard:
    """A reference-model card (`card_type: reference_model`) — the shared
    system landscape the situation cards point at via `stack_ref`.

    `systems` / `interfaces` / `known_blind_spots` are the descriptive
    specification. `entity_refs` / `stack_edges` are the same content made into
    a loadable graph; `has_graph` is True when they are present (they are, for
    `MODEL-AMO-PLANT-IT`)."""

    id: str
    domain: str
    name: str
    purpose: str
    systems: list[SystemDef]
    interfaces: list[Interface]
    known_blind_spots: list[BlindSpot]
    entity_refs: list[Entity] = field(default_factory=list)
    stack_edges: list[Edge] = field(default_factory=list)
    example_queries: list[ExampleQuery] = field(default_factory=list)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def has_graph(self) -> bool:
        return bool(self.entity_refs)

    @property
    def system_classes(self) -> set[str]:
        """Every system_class this model's :System nodes will actually carry
        once loaded — the resolvability check compares against this, not
        against `systems` (the descriptive table), because a system_class can
        be described there without a matching graph node existing."""
        return {
            e.props["system_class"]
            for e in self.entity_refs
            if e.label == "System" and "system_class" in e.props
        }

    @property
    def write_semantics_by_object_name(self) -> dict[str, str]:
        """v0.5 §2.12 — normalised DataObject name -> APPEND_ONLY | UPDATABLE,
        for every :DataObject entity_ref that declares one. Keyed on the
        normalised name (lower, alnum-joined) so an instance node label like
        `Confirmation` can be matched against `Operation confirmation`."""
        out: dict[str, str] = {}
        for e in self.entity_refs:
            if e.label != "DataObject":
                continue
            ws = e.props.get("write_semantics")
            if ws:
                norm = "".join(re.findall(r"[a-z0-9]+", str(e.props.get("name", "")).lower()))
                if norm:
                    out[norm] = str(ws)
        return out


@dataclass
class Dataset:
    situations: list[Card]
    reference_models: list[ReferenceModelCard]
    skipped_blocks: int


def parse_file(path: str | Path) -> Dataset:
    """Parse every card (situation + reference-model) in the markdown file."""
    text = Path(path).read_text(encoding="utf-8")
    situations: list[Card] = []
    reference_models: list[ReferenceModelCard] = []
    skipped = 0

    for raw_block in _YAML_FENCE_RE.findall(text):
        try:
            data = yaml.safe_load(raw_block)
        except yaml.YAMLError as exc:
            raise CardParseError(f"a ```yaml block did not parse: {exc}") from exc
        if not isinstance(data, dict):
            skipped += 1
            continue

        cid = str(data.get("id", "")).strip()
        card_type = str(data.get("card_type", "")).strip()

        if card_type == "situation" and SITUATION_ID_RE.match(cid):
            situations.append(_situation_from_dict(data, cid))
        elif card_type == "reference_model" and MODEL_ID_RE.match(cid):
            reference_models.append(_reference_model_from_dict(data, cid))
        else:
            skipped += 1  # schema-template block or something else, not a card

    ids = [c.id for c in situations] + [m.id for m in reference_models]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CardParseError(f"duplicate card id(s): {sorted(dupes)}")

    return Dataset(situations=situations, reference_models=reference_models, skipped_blocks=skipped)


# ── situation cards ──────────────────────────────────────────────────────────


def _situation_from_dict(data: dict, cid: str) -> Card:
    domain = str(data.get("domain", "")).strip()
    if domain not in VALID_DOMAINS:
        raise CardParseError(f"{cid}: domain {domain!r} not in {sorted(VALID_DOMAINS)}")

    stack_ref = str(data.get("stack_ref", "")).strip()
    if not MODEL_ID_RE.match(stack_ref):
        raise CardParseError(f"{cid}: stack_ref {stack_ref!r} is not a MODEL-<DOMAIN>-... id")

    sor = data.get("system_of_record") or {}
    entities = _parse_entities(cid, data.get("entity_refs"))
    entity_ids = {e.id for e in entities}
    edges = _parse_edges(cid, data.get("edges"), entity_ids)

    trigger = data.get("trigger") or {}
    source = _parse_trigger_source(cid, trigger.get("source"))
    detectability = str(trigger.get("detectability", "")).strip()
    if detectability not in VALID_DETECTABILITY:
        raise CardParseError(
            f"{cid}: trigger.detectability {detectability!r} not in {sorted(VALID_DETECTABILITY)}"
        )
    condition = str(trigger.get("condition", "")).strip()
    pattern = str(trigger.get("pattern", "")).strip()
    if not condition:
        raise CardParseError(f"{cid}: trigger.condition is empty")
    if not pattern:
        raise CardParseError(f"{cid}: trigger.pattern is empty")
    _require_domain_scoped_pattern(cid, pattern)

    solver_boundary = str(data.get("solver_boundary", "")).strip()
    if not solver_boundary:
        raise CardParseError(f"{cid}: solver_boundary is empty")

    sample = _parse_sample_instance(cid, data.get("sample_instance"), entity_ids)
    strategies = _parse_strategies(cid, data.get("strategies"))

    entity_labels = {e.id: e.label for e in entities}
    tracked = _parse_tracked_transitions(cid, data.get("tracked_transitions"), set(entity_labels.values()))
    temporal_semantics = data.get("temporal_semantics") if isinstance(data.get("temporal_semantics"), dict) else {}

    qual = data.get("qualifier_test") or {}
    classification = str(qual.get("classification", "")).strip()
    if classification not in VALID_CLASSIFICATIONS:
        raise CardParseError(
            f"{cid}: qualifier_test.classification {classification!r} not in "
            f"{sorted(VALID_CLASSIFICATIONS)}"
        )

    return Card(
        id=cid,
        domain=domain,
        name=str(data.get("name", "")).strip(),
        stack_ref=stack_ref,
        source_systems=[str(s) for s in (sor.get("source_systems") or [])],
        object_path=str(sor.get("object_path", "")).strip(),
        entities=entities,
        edges=edges,
        trigger_source=source,
        detectability=detectability,
        trigger_condition=condition,
        trigger_pattern=pattern,
        pattern_note=_opt_str(data.get("trigger", {}).get("pattern_note")) or _opt_str(data.get("pattern_note")),
        solver_boundary=solver_boundary,
        detectability_note=_opt_str(data.get("detectability_note")),
        tracked_transitions=tracked,
        temporal_semantics={k: v for k, v in temporal_semantics.items() if k != "note"},
        context_features=_parse_context_features(data.get("context_features")),
        sample_instance=sample,
        strategies=strategies,
        qualifier_divergence=str(qual.get("practitioner_divergence", "")).strip(),
        qualifier_rationale=str(qual.get("rationale", "")).strip(),
        qualifier_classification=classification,
        raw=data,
    )


def _require_domain_scoped_pattern(cid: str, pattern: str) -> None:
    """Every fresh node binding in trigger.pattern must carry `{domain: $domain}`.
    One Memgraph instance can hold more than one domain; isolation depends on the
    patterns enforcing it themselves, not on the MCP process's DOMAIN env var
    alone (that only decides which patterns run)."""
    offenders = [
        m for m in _NODE_WITH_LABEL_RE.findall(pattern) if not m or "$domain" not in m
    ]
    if offenders:
        raise CardParseError(
            f"{cid}: trigger.pattern has a labeled node without {{domain: $domain}} "
            f"({len(offenders)} occurrence(s)) — every node must be domain-scoped"
        )


def _parse_tracked_transitions(
    cid: str, raw: Any, entity_labels: set[str]
) -> list[TrackedTransition]:
    """v0.5 §2.11 / the parser check. `retains` must be exactly 1 — a hard bound,
    not a default. Anything higher is a revision chain wearing a different name
    and is rejected at load (raising here fails the parse, which fails the
    load). `node_type` must be one of the card's own entity labels."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise CardParseError(f"{cid}: tracked_transitions present but not a non-empty list")
    out: list[TrackedTransition] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CardParseError(f"{cid}: tracked_transitions entry not a mapping: {item!r}")
        node_type = str(item.get("node_type", "")).strip()
        fld = str(item.get("field", "")).strip()
        retains = item.get("retains")
        if not node_type or not fld:
            raise CardParseError(f"{cid}: tracked_transitions entry needs node_type and field")
        if retains != 1:
            raise CardParseError(
                f"{cid}: tracked_transitions[{node_type}.{fld}].retains is {retains!r}, "
                f"must be exactly 1 — anything higher is a revision chain (§2.11)"
            )
        if node_type not in entity_labels:
            raise CardParseError(
                f"{cid}: tracked_transitions node_type {node_type!r} is not one of this "
                f"card's entity labels {sorted(entity_labels)}"
            )
        out.append(TrackedTransition(node_type=node_type, field=fld, note=_opt_str(item.get("note"))))
    return out


def _parse_trigger_source(cid: str, raw: Any) -> TriggerSource:
    if not isinstance(raw, dict) or not raw:
        raise CardParseError(f"{cid}: trigger.source missing")
    system_class = str(raw.get("system_class", "")).strip()
    emission_mode = str(raw.get("emission_mode", "")).strip()
    latency_class = str(raw.get("latency_class", "")).strip()
    if not (system_class and emission_mode and latency_class):
        raise CardParseError(f"{cid}: trigger.source missing system_class/emission_mode/latency_class")
    return TriggerSource(
        system_class=system_class,
        emission_mode=emission_mode,
        latency_class=latency_class,
        reference_vendor=_opt_str(raw.get("reference_vendor")),
        emitting_object=_opt_str(raw.get("emitting_object")),
    )


def _parse_entities(cid: str, raw: Any, *, require: bool = True) -> list[Entity]:
    """Shared by situation cards and reference-model graphs. Any key beyond
    `id` / `type` is captured as a node property (`Entity.props`) — bare for
    situation cards, populated for reference-model entity_refs (system_class,
    isa95_level, name, …)."""
    if not isinstance(raw, list) or not raw:
        if require:
            raise CardParseError(f"{cid}: entity_refs missing or empty")
        return []
    entities: list[Entity] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or "id" not in item or "type" not in item:
            raise CardParseError(f"{cid}: entity_ref entry malformed: {item!r}")
        eid = str(item["id"]).strip()
        label = str(item["type"]).strip()
        if not _LABEL_RE.match(label):
            raise CardParseError(f"{cid}: entity {eid} has non-label type {label!r}")
        if eid in seen:
            raise CardParseError(f"{cid}: entity id {eid} listed twice")
        seen.add(eid)
        props = {str(k): v for k, v in item.items() if k not in ("id", "type")}
        entities.append(Entity(id=eid, label=label, props=props))
    return entities


def _parse_edges(
    cid: str, raw: Any, entity_ids: set[str], *, require: bool = True, strict_endpoints: bool = True
) -> list[Edge]:
    """`strict_endpoints=False` for reference-model graphs, whose `edges` list
    references reified BlindSpot ids (BLIND-*) that are not declared in
    `entity_refs` — those are handled via `known_blind_spots` instead. Any key
    beyond from/relationship/to is captured as an edge property (SENDS carries
    `carries` + `cadence`)."""
    if not isinstance(raw, list) or not raw:
        if require:
            raise CardParseError(f"{cid}: edges missing or empty")
        return []
    edges: list[Edge] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CardParseError(f"{cid}: edge entry not a mapping: {item!r}")
        src = str(item.get("from", "")).strip()
        rel = str(item.get("relationship", "")).strip()
        dst = str(item.get("to", "")).strip()
        if not _REL_RE.match(rel):
            raise CardParseError(f"{cid}: edge relationship {rel!r} is not UPPER_SNAKE")
        if strict_endpoints:
            for endpoint in (src, dst):
                if endpoint not in entity_ids:
                    raise CardParseError(f"{cid}: edge endpoint {endpoint!r} is not in entity_refs")
        props = {str(k): v for k, v in item.items() if k not in ("from", "relationship", "to")}
        edges.append(Edge(src=src, rel=rel, dst=dst, props=props))
    return edges


def _parse_sample_instance(cid: str, raw: Any, entity_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or not raw:
        raise CardParseError(f"{cid}: sample_instance missing or empty")
    out: dict[str, dict[str, Any]] = {}
    for key, props in raw.items():
        key = str(key).strip()
        if key not in entity_ids:
            raise CardParseError(f"{cid}: sample_instance key {key!r} is not one of this card's entities")
        if not isinstance(props, dict):
            raise CardParseError(f"{cid}: sample_instance[{key}] is not a mapping")
        out[key] = {str(k): _coerce_scalar(v) for k, v in props.items()}
    return out


def _parse_strategies(cid: str, raw: Any) -> list[Strategy]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise CardParseError(f"{cid}: expected >= 2 strategies, got {raw!r}")
    strategies: list[Strategy] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CardParseError(f"{cid}: strategy entry not a mapping: {item!r}")
        pre = item.get("preconditions") or []
        if isinstance(pre, str):
            pre = [pre]
        action_paths = _parse_action_paths(cid, item.get("id", "?"), item.get("system_of_action"))
        ceiling = str(item.get("delegation_ceiling", "")).strip()
        if not ceiling:
            raise CardParseError(f"{cid}: strategy {item.get('id')} missing delegation_ceiling")
        strategies.append(
            Strategy(
                id=str(item.get("id", "")).strip(),
                name=str(item.get("name", "")).strip(),
                doctrine=str(item.get("doctrine", "")).strip(),
                preconditions=[str(p).strip() for p in pre],
                trade_off=str(item.get("trade_off", "")).strip(),
                action_paths=action_paths,
                delegation_ceiling=ceiling,
                known_limitation=_opt_str(item.get("known_limitation")),
            )
        )
    return strategies


def _parse_action_paths(cid: str, strat_id: str, raw: Any) -> list[ActionPath]:
    if not isinstance(raw, list) or not raw:
        raise CardParseError(f"{cid}/{strat_id}: system_of_action missing or empty")
    out: list[ActionPath] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CardParseError(f"{cid}/{strat_id}: system_of_action entry not a mapping: {item!r}")
        writes = item.get("writes") or []
        if isinstance(writes, str):
            writes = [writes]
        out.append(
            ActionPath(
                execution_path=str(item.get("execution_path", "")).strip(),
                system_class=str(item.get("system_class", "")).strip(),
                operation=str(item.get("operation", "")).strip(),
                writes=[str(w).strip() for w in writes],
                reversibility=str(item.get("reversibility", "")).strip(),
                authority=str(item.get("authority", "")).strip(),
                endpoint=_opt_str(item.get("endpoint")),
            )
        )
    return out


def _parse_context_features(raw: Any) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            out.extend(str(v).strip() for v in item.values())
        else:
            out.append(str(item).strip())
    return out


# ── reference-model cards ────────────────────────────────────────────────────


def _reference_model_from_dict(data: dict, cid: str) -> ReferenceModelCard:
    domain = str(data.get("domain", "")).strip()
    if domain not in VALID_DOMAINS:
        raise CardParseError(f"{cid}: domain {domain!r} not in {sorted(VALID_DOMAINS)}")

    systems_raw = data.get("systems")
    if not isinstance(systems_raw, list) or not systems_raw:
        raise CardParseError(f"{cid}: systems missing or empty")
    systems = [_system_def_from_dict(cid, s) for s in systems_raw]

    interfaces = [
        _interface_from_dict(cid, i) for i in (data.get("interfaces") or [])
    ]
    blind_spots = [
        _blind_spot_from_dict(cid, b) for b in (data.get("known_blind_spots") or [])
    ]

    # The stack as a graph — `entity_refs` / `edges` on the reference model.
    entity_refs = _parse_entities(cid, data.get("entity_refs"), require=False)
    stack_edges = _parse_edges(
        cid, data.get("edges"), {e.id for e in entity_refs},
        require=False, strict_endpoints=False,
    )
    example_queries = _parse_example_queries(cid, data.get("queries_this_enables"))

    model = ReferenceModelCard(
        id=cid,
        domain=domain,
        name=str(data.get("name", "")).strip(),
        purpose=_opt_str(data.get("purpose")) or "",
        systems=systems,
        interfaces=interfaces,
        known_blind_spots=blind_spots,
        entity_refs=entity_refs,
        stack_edges=stack_edges,
        example_queries=example_queries,
        raw=data,
    )

    if model.has_graph:
        # Every system_class named in the spec table must have a matching
        # :System node in the graph, or a situation card that resolves against
        # this model would fail on a value the model itself lists.
        declared = {s.system_class for s in systems}
        graphed = model.system_classes
        missing = declared - graphed
        if missing:
            raise CardParseError(
                f"{cid}: system_class(es) {sorted(missing)} are in `systems` but have no "
                f":System node in `entity_refs` — the graph and the spec table disagree"
            )
        # v0.5 §2.12 / §3 — every :DataObject in a graph-backed model must
        # declare write_semantics (APPEND_ONLY | UPDATABLE). The §8 append-only
        # assertion cannot run on an object with no declared semantics.
        for e in model.entity_refs:
            if e.label != "DataObject":
                continue
            ws = e.props.get("write_semantics")
            if ws is None:
                raise CardParseError(
                    f"{cid}: DataObject {e.id} ({e.props.get('name')!r}) has no write_semantics "
                    f"— required on every :DataObject in a graph-backed model (§2.12)"
                )
            if str(ws) not in VALID_WRITE_SEMANTICS:
                raise CardParseError(
                    f"{cid}: DataObject {e.id} write_semantics {ws!r} not in "
                    f"{sorted(VALID_WRITE_SEMANTICS)}"
                )
    return model


def _parse_example_queries(cid: str, raw: Any) -> list[ExampleQuery]:
    if not isinstance(raw, list):
        return []
    out: list[ExampleQuery] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _opt_str(item.get("name"))
        cypher = _opt_str(item.get("cypher"))
        if name and cypher:
            out.append(ExampleQuery(name=name, cypher=cypher, note=_opt_str(item.get("note"))))
    return out


def _system_def_from_dict(cid: str, item: Any) -> SystemDef:
    if not isinstance(item, dict):
        raise CardParseError(f"{cid}: systems entry not a mapping: {item!r}")
    system_class = str(item.get("system_class", "")).strip()
    if not system_class:
        raise CardParseError(f"{cid}: a systems entry has no system_class")
    key_ids = item.get("key_identifiers")
    if key_ids is None:
        single = item.get("key_identifier")
        key_ids = [single] if single else []
    elif isinstance(key_ids, str):
        key_ids = [key_ids]
    dws = _opt_str(item.get("default_write_semantics"))
    if dws is not None and dws not in VALID_WRITE_SEMANTICS:
        raise CardParseError(
            f"{cid}: {system_class} default_write_semantics {dws!r} not in {sorted(VALID_WRITE_SEMANTICS)}"
        )
    return SystemDef(
        system_class=system_class,
        isa95_level=str(item.get("isa95_level", "")).strip(),
        role=_opt_str(item.get("role")) or "",
        emits=[str(e).strip() for e in (item.get("emits") or [])],
        accepts_writes=[str(a).strip() for a in (item.get("accepts_writes") or [])],
        latency=str(item.get("latency", "")).strip(),
        key_identifiers=[str(k).strip() for k in key_ids],
        note=_opt_str(item.get("note")),
        default_write_semantics=dws,
    )


def _interface_from_dict(cid: str, item: Any) -> Interface:
    if not isinstance(item, dict):
        raise CardParseError(f"{cid}: interfaces entry not a mapping: {item!r}")
    src = str(item.get("from", "")).strip()
    dst = str(item.get("to", "")).strip()
    if not (src and dst):
        raise CardParseError(f"{cid}: interface entry missing from/to: {item!r}")
    return Interface(
        src=src,
        dst=dst,
        carries=_opt_str(item.get("carries")) or "",
        cadence=str(item.get("cadence", "")).strip(),
        note=_opt_str(item.get("note")),
    )


def _blind_spot_from_dict(cid: str, item: Any) -> BlindSpot:
    if not isinstance(item, dict):
        raise CardParseError(f"{cid}: known_blind_spots entry not a mapping: {item!r}")
    between = item.get("between") or []
    if not isinstance(between, list) or len(between) < 2:
        raise CardParseError(f"{cid}: known_blind_spots.between needs >= 2 systems: {item!r}")
    return BlindSpot(
        systems=[str(s).strip() for s in between],
        gap=_opt_str(item.get("gap")) or "",
        card_id=_opt_str(item.get("card")),
    )


# ── shared helpers ────────────────────────────────────────────────────────────


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _coerce_scalar(value: Any) -> Any:
    """Normalise a YAML scalar for use as a graph property.

    YAML already gives us int / float / bool / date. An ISO date that slipped
    through as a string is converted here so temporal predicates in a
    trigger.pattern (e.g. date subtraction) have real dates to work with.
    """
    if isinstance(value, str):
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
        if m:
            return _dt.date(int(m[1]), int(m[2]), int(m[3]))
    return value
