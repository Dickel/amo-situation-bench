"""Graph layer against a live Memgraph.

Requires a reachable Memgraph seeded by `loader.load` and `MEMGRAPH_URI` set.
Skipped otherwise.

    MEMGRAPH_URI=bolt://127.0.0.1:7687 pytest mcp_server/tests/test_graph_live.py
"""

from __future__ import annotations

import os

import pytest

from mcp_server.graph import GraphClient

URI = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")


def _client(domain: str) -> GraphClient:
    try:
        c = GraphClient(domain, URI)
        c.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Memgraph at {URI}: {exc}")
    return c


@pytest.fixture
def amo():
    c = _client("AMO")
    yield c
    c.close()


def test_get_strategies_returns_action_paths_ceiling_and_solver_boundary(amo):
    meta, rows, _ = amo.get_strategies("SIT-AMO-001")
    assert meta is not None
    assert meta["solver_boundary"]
    assert len(rows) >= 2
    for r in rows:
        assert r["delegation_ceiling"]
        assert r["action_paths"], f"strategy {r['id']} has no action_paths"
        for ap in r["action_paths"]:
            assert ap["execution_path"]
            assert ap["reversibility"]


def test_explain_qualifier_returns_solver_boundary(amo):
    row, _ = amo.explain_qualifier("SIT-AMO-001")
    assert row is not None
    assert row["solver_boundary"]
    assert row["classification"] == "judgment"


# ── v0.5: provenance / bitemporality on the MCP surface ────────────────────


def test_explain_qualifier_carries_temporal_semantics_and_tracked_transition(amo):
    row, _ = amo.explain_qualifier("SIT-AMO-002")
    assert row is not None
    tt = row["tracked_transitions"]
    assert len(tt) == 1 and tt[0]["node_type"] == "POLine" and tt[0]["field"] == "promise_date"
    assert tt[0]["retains"] == 1
    axes = dict(x.split("=") for x in row["temporal_semantics"])
    assert axes["promise_date_changed_at"] == "graph_updated_at"


def test_cards_without_a_tracked_transition_return_an_empty_list(amo):
    row, _ = amo.explain_qualifier("SIT-AMO-001")
    assert row["tracked_transitions"] == []


def test_get_strategies_surfaces_known_limitation(amo):
    _, rows, _ = amo.get_strategies("SIT-AMO-002")
    s1 = next(r for r in rows if r["id"] == "S1")
    assert s1["known_limitation"] and "retains: 1" in s1["known_limitation"]


def test_stack_model_data_objects_carry_write_semantics(amo):
    m, _ = amo.get_stack_model()
    sem = {o["name"]: o["write_semantics"] for o in m["data_objects"]}
    assert all(v in {"APPEND_ONLY", "UPDATABLE"} for v in sem.values())
    assert sem["Operation confirmation"] == "APPEND_ONLY"
    assert sem["Work order"] == "UPDATABLE"
    by_class = {s["system_class"]: s.get("default_write_semantics") for s in m["systems"]}
    assert by_class["MES"] == "APPEND_ONLY"
    assert by_class["ERP"] == "UPDATABLE"


def test_unknown_situation_id_returns_nothing(amo):
    meta, rows, _ = amo.get_strategies("SIT-AMO-404")
    assert meta is None
    assert rows == []
    row, _ = amo.explain_qualifier("SIT-AMO-404")
    assert row is None


def test_match_situations_fires_on_known_instance(amo):
    result, _ = amo.match_situations("WO-4471")
    assert result["found"] is True
    matched = {m["situation_id"] for m in result["matches"]}
    assert "SIT-AMO-001" in matched


def test_match_situations_shared_entity_hits_both_cards(amo):
    # WO-4471 deliberately appears in both SIT-AMO-001 and SIT-AMO-004. If only
    # one comes back, entity_refs isn't resolving to a single shared node.
    result, _ = amo.match_situations("WO-4471")
    matched = {m["situation_id"] for m in result["matches"]}
    assert {"SIT-AMO-001", "SIT-AMO-004"}.issubset(matched)


def test_match_situations_unknown_entity_is_reported_not_crashed(amo):
    result, _ = amo.match_situations("DOES-NOT-EXIST")
    assert result["found"] is False
    assert result["matches"] == []


def test_get_stack_model_amo_is_a_graph(amo):
    m, _ = amo.get_stack_model()
    assert m["id"] == "MODEL-AMO-PLANT-IT"
    assert m["has_graph"] is True
    assert len(m["systems"]) == 9
    assert len(m["interfaces"]) >= 9
    assert len(m["known_blind_spots"]) >= 3
    # v0.4: the graph node classes and the example queries
    assert len(m["data_objects"]) == 18
    assert len(m["business_processes"]) == 8
    assert len(m["standards"]) == 5
    assert len(m["example_queries"]) == 3
    assert all(q["cypher"] for q in m["example_queries"])
    # every blind spot is covered by a real situation card
    assert all(bs["covered_by"] for bs in m["known_blind_spots"])
    # a reified interface carries an object + a cadence
    assert any(i["carries"] and i["cadence"] for i in m["interfaces"])


def test_get_stack_model_is_domain_scoped(amo):
    m, _ = amo.get_stack_model()
    classes = {s["system_class"] for s in m["systems"]}
    assert "TMS" not in classes
    assert "PAYMENT_RAIL" not in classes


def test_situation_footprint_traces_amo_card_across_systems(amo):
    fp, _ = amo.get_situation_footprint("SIT-AMO-005")
    assert fp["detected_by"] == "MES"
    assert set(fp["evidence_systems"]) == {"MES", "ERP", "IBP_SOP"}
    assert "HUMAN_ROUTINE" in fp["acts_on_systems"]
    assert fp["covers_blind_spots"]
    assert fp["cross_system_enforcement"] is True


def test_situation_footprint_unknown_id(amo):
    fp, _ = amo.get_situation_footprint("SIT-AMO-999")
    assert fp is None


# ── agent-support tools (AMO agent roster v0.1) ────────────────────────────


def test_get_skill_by_situation(amo):
    sk, _ = amo.get_skill("SIT-AMO-001")
    assert sk["name"] == "amo-part-contention"
    assert sk["classification"] == "judgment"
    assert sk["situation_id"] == "SIT-AMO-001"
    assert sk["body"].startswith("#")
    assert "match_situations" in sk["allowed_tools"]


def test_get_skill_triage_for_empty_id(amo):
    sk, _ = amo.get_skill("")
    assert sk["name"] == "amo-situation-triage"
    assert sk["classification"] == "meta"
    assert sk["situation_id"] is None


def test_get_skill_absent_for_card_without_one(amo):
    sk, _ = amo.get_skill("SIT-AMO-002")   # no skill authored yet
    assert sk is None


def test_read_commitments_from_situation(amo):
    r, _ = amo.read_commitments("SIT-AMO-004")
    assert r["found"] is True
    by_wo = {c["work_order"]: c for c in r["commitments"]}
    assert set(by_wo) == {"WO-4471", "WO-4503"}
    assert by_wo["WO-4471"]["customer"] == "CUST-NOVASAT"
    assert by_wo["WO-4471"]["customer_tier"] == 1


def test_read_commitments_from_work_order(amo):
    r, _ = amo.read_commitments("WO-7210")
    assert [c["customer"] for c in r["commitments"]] == ["CUST-NOVASAT"]
    assert r["commitments"][0]["accepts_partial_shipment"] == "unknown"


def test_read_commitments_unknown_entity(amo):
    r, _ = amo.read_commitments("NOPE-1")
    assert r["found"] is False
    assert r["commitments"] == []


def test_read_order_context(amo):
    ctx, _ = amo.read_order_context("WO-4471")
    assert ctx["work_order"]["status"] == "released"
    assert ctx["work_order"]["source_system_class"] == "ERP"
    assert isinstance(ctx["work_order"]["source_valid_from"], str)  # datetime -> ISO
    assert [p["id"] for p in ctx["parts"]] == ["PART-XR200"]
    assert ctx["operations"][0]["id"] == "OP-4471-0020"
    assert ctx["programs"] == ["PROG-31"]
    assert set(ctx["in_situations"]) == {"SIT-AMO-001", "SIT-AMO-004"}


def test_read_order_context_unknown(amo):
    ctx, _ = amo.read_order_context("WO-9999")
    assert ctx is None