"""Parser tests — pure Python, no database. Run: `pytest` from the repo root."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from loader.cards import MODEL_ID_RE, SITUATION_ID_RE, CardParseError, parse_file

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "amo-situations.md"


@pytest.fixture(scope="module")
def ds():
    return parse_file(DATA_FILE)


def test_expected_counts(ds):
    assert len(ds.situations) == 5
    assert len(ds.reference_models) == 1
    assert all(c.domain == "AMO" for c in ds.situations)


def test_schema_template_blocks_are_skipped(ds):
    # Section 2 has three template blocks (a short stub, the full situation
    # schema, and the tracked_transitions example) — none a real card.
    assert ds.skipped_blocks == 3


def test_ids_unique_and_well_formed(ds):
    sit_ids = [c.id for c in ds.situations]
    model_ids = [m.id for m in ds.reference_models]
    assert len(sit_ids) == len(set(sit_ids))
    assert all(SITUATION_ID_RE.match(i) for i in sit_ids)
    assert all(MODEL_ID_RE.match(i) for i in model_ids)


def test_every_situation_points_at_a_real_reference_model(ds):
    model_ids = {m.id for m in ds.reference_models}
    for c in ds.situations:
        assert c.stack_ref in model_ids, f"{c.id}: stack_ref {c.stack_ref!r} not a loaded model"


def test_every_edge_endpoint_is_a_declared_entity(ds):
    for c in ds.situations:
        for e in c.edges:
            assert e.src in c.entity_ids, f"{c.id}: {e.src}"
            assert e.dst in c.entity_ids, f"{c.id}: {e.dst}"


def test_every_sample_instance_key_is_a_declared_entity(ds):
    for c in ds.situations:
        for key in c.sample_instance:
            assert key in c.entity_ids, f"{c.id}: {key}"


def test_every_trigger_pattern_is_domain_scoped(ds):
    # Parsing itself enforces this (CardParseError otherwise) - this test just
    # asserts every card actually made it through, i.e. the check didn't
    # silently swallow a violation.
    assert all("$domain" in c.trigger_pattern for c in ds.situations)


def test_cards_have_triggers_solver_boundary_and_strategies(ds):
    for c in ds.situations:
        assert c.trigger_condition
        assert c.solver_boundary
        assert len(c.strategies) >= 2
        assert c.qualifier_classification in {"judgment", "solver"}
        assert c.detectability in {"DIRECT", "DERIVED", "ABSENT"}


def test_every_strategy_has_at_least_one_action_path_and_a_ceiling(ds):
    for c in ds.situations:
        for s in c.strategies:
            assert s.action_paths, f"{c.id}/{s.id}: no system_of_action"
            assert s.delegation_ceiling


def test_all_current_situations_are_judgment(ds):
    # If this ever fails, a solver card was added - loader skips it by design.
    assert all(c.is_judgment for c in ds.situations)


def test_iso_dates_become_date_objects(ds):
    amo1 = next(c for c in ds.situations if c.id == "SIT-AMO-001")
    assert amo1.sample_instance["WO-4471"]["need_date"] == dt.date(2026, 9, 10)


def test_shared_entity_across_two_cards(ds):
    # WO-4471 appears in both SIT-AMO-001 and SIT-AMO-004 by design (Appendix
    # A3) - the loader must resolve it to one node, not two.
    amo1 = next(c for c in ds.situations if c.id == "SIT-AMO-001")
    amo4 = next(c for c in ds.situations if c.id == "SIT-AMO-004")
    assert "WO-4471" in amo1.entity_ids
    assert "WO-4471" in amo4.entity_ids


def test_reference_model_has_systems_and_blind_spots(ds):
    m = ds.reference_models[0]
    assert m.id == "MODEL-AMO-PLANT-IT"
    assert len(m.systems) >= 9
    assert len(m.interfaces) >= 9
    assert len(m.known_blind_spots) >= 3
    sit_ids = {c.id for c in ds.situations}
    for bs in m.known_blind_spots:
        if bs.card_id:
            assert bs.card_id in sit_ids, f"blind spot points at unknown card {bs.card_id}"


# ── reference model as a graph ─────────────────────────────────────────────


def test_model_has_a_graph(ds):
    m = ds.reference_models[0]
    assert m.has_graph


def test_amo_graph_node_and_edge_shape(ds):
    amo = ds.reference_models[0]
    labels = {}
    for e in amo.entity_refs:
        labels[e.label] = labels.get(e.label, 0) + 1
    assert labels == {"System": 9, "DataObject": 18, "BusinessProcess": 8, "Standard": 5}
    rels = {x.rel for x in amo.stack_edges}
    assert {"EXECUTES", "MASTERS", "CONSUMES", "PRODUCES", "SENDS", "COMPLIES_WITH"} <= rels
    # SENDS edges carry the object they carry + a cadence
    sends = [x for x in amo.stack_edges if x.rel == "SENDS"]
    assert sends and all("carries" in x.props and "cadence" in x.props for x in sends)


def test_every_situation_system_class_resolves_for_amo(ds):
    amo = ds.reference_models[0]
    graphed = amo.system_classes
    for c in ds.situations:
        if c.stack_ref != amo.id:
            continue
        refs = [c.trigger_source.system_class, *c.source_systems]
        for s in c.strategies:
            refs += [ap.system_class for ap in s.action_paths]
        unresolved = sorted({r for r in refs if r not in graphed})
        assert not unresolved, f"{c.id}: {unresolved} not a :System in {amo.id}"


def test_amo_model_has_example_queries(ds):
    amo = ds.reference_models[0]
    assert len(amo.example_queries) == 3
    assert all(q.name and q.cypher for q in amo.example_queries)


def test_reference_entity_props_captured(ds):
    amo = ds.reference_models[0]
    sys_erp = next(e for e in amo.entity_refs if e.id == "SYS-ERP")
    assert sys_erp.props["system_class"] == "ERP"
    obj = next(e for e in amo.entity_refs if e.label == "DataObject")
    assert "name" in obj.props


# ── v0.5: provenance / bitemporality ───────────────────────────────────────


def test_amo_data_objects_all_declare_write_semantics(ds):
    amo = ds.reference_models[0]
    objs = [e for e in amo.entity_refs if e.label == "DataObject"]
    assert len(objs) == 18
    assert all(e.props.get("write_semantics") in {"APPEND_ONLY", "UPDATABLE"} for e in objs)
    ws = amo.write_semantics_by_object_name
    assert ws["operationconfirmation"] == "APPEND_ONLY"
    assert ws["workorder"] == "UPDATABLE"


def test_amo_system_default_write_semantics(ds):
    amo = ds.reference_models[0]
    by_class = {s.system_class: s for s in amo.systems}
    assert by_class["ERP"].default_write_semantics == "UPDATABLE"
    assert by_class["MES"].default_write_semantics == "APPEND_ONLY"
    assert by_class["SCADA_HISTORIAN"].default_write_semantics is None


def test_sit_amo_002_tracked_transition(ds):
    c = next(c for c in ds.situations if c.id == "SIT-AMO-002")
    assert len(c.tracked_transitions) == 1
    tt = c.tracked_transitions[0]
    assert (tt.node_type, tt.field) == ("POLine", "promise_date")
    # retains: 1 is enforced (parser would have raised otherwise)
    assert c.temporal_semantics["promise_date_changed_at"] == "graph_updated_at"


def test_sit_amo_002_pattern_uses_declared_transition_not_undeclared_fields(ds):
    c = next(c for c in ds.situations if c.id == "SIT-AMO-002")
    assert "promise_date_prior" in c.trigger_pattern
    assert "original_promise_date" not in c.trigger_pattern
    assert "revised_promise_date" not in c.trigger_pattern
    # duration.between() does not exist on Memgraph (D5.3) — Neo4j-only, must not be present
    assert "duration.between" not in c.trigger_pattern


def test_no_trigger_pattern_uses_duration_between(ds):
    # duration.between is Neo4j-only; direct date subtraction is used instead
    # and 005; the repo copy rewrites both to direct date subtraction.
    for c in ds.situations:
        assert "duration.between" not in c.trigger_pattern, c.id


def test_sit_amo_002_s1_known_limitation(ds):
    c = next(c for c in ds.situations if c.id == "SIT-AMO-002")
    assert c.strategies[0].known_limitation
    assert "retains: 1" in c.strategies[0].known_limitation


def test_tracked_transition_retains_must_be_one():
    bad = """```yaml
id: SIT-AMO-999
domain: AMO
card_type: situation
name: x
stack_ref: MODEL-AMO-PLANT-IT
system_of_record: {source_systems: [ERP], object_path: A}
entity_refs:
  - {id: POL-1, type: POLine}
edges:
  - {from: POL-1, relationship: SELF, to: POL-1}
tracked_transitions:
  - {node_type: POLine, field: promise_date, retains: 2}
trigger:
  source: {system_class: ERP, emission_mode: EVENT, latency_class: HOURS}
  detectability: DERIVED
  condition: x
  pattern: "MATCH (p:POLine {domain: $domain}) RETURN p"
solver_boundary: x
sample_instance: {POL-1: {promise_date: 2026-01-01}}
strategies:
  - {id: S1, name: a, doctrine: a, trade_off: a, delegation_ceiling: RECOMMEND,
     system_of_action: [{execution_path: NO_ACTION, system_class: ERP, operation: x,
     writes: [], reversibility: REVERSIBLE, authority: x}]}
  - {id: S2, name: b, doctrine: b, trade_off: b, delegation_ceiling: RECOMMEND,
     system_of_action: [{execution_path: NO_ACTION, system_class: ERP, operation: x,
     writes: [], reversibility: REVERSIBLE, authority: x}]}
qualifier_test: {practitioner_divergence: "yes", rationale: x, classification: judgment}
```"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(bad)
        path = fh.name
    with pytest.raises(CardParseError, match="retains"):
        parse_file(path)
