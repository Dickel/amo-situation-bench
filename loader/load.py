"""Seed Memgraph from the AMO situations markdown.

    python -m loader.load [--file data/amo-situations.md] [--keep]
                          [--include-solver] [--skip-provenance-check] [--dry-run]

The wipe + rebuild runs in one transaction, so a concurrent reader never sees a
half-built graph.

--dry-run prints the Cypher and touches no database.
--keep skips the initial `MATCH (n) DETACH DELETE n` wipe.
--include-solver loads situation cards classified `solver` too (skipped by
  default — solver situations are not part of the taxonomy).
--skip-provenance-check runs the load even if the provenance assertions
  fail (local iteration only).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cards import (
    Card,
    EXTRACTED_NODE_LABELS,
    PROVENANCE_KEYS,
    ReferenceModelCard,
    parse_file,
)
from .skills import SkillDoc, parse_skills_dir
from . import db

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = _REPO_ROOT / "data" / "amo-situations.md"
DEFAULT_SKILLS_DIR = _REPO_ROOT / "skills"

# v0.5 §2.10 — the properties an extracted node must carry *once it presents as
# extracted at all* (i.e. carries any provenance key). A sample_instance node
# carrying none is an illustrative stub and is allowed (§2.10: "omit it
# elsewhere"); one carrying some but not these is internally incomplete.
_REQUIRED_PROVENANCE = {
    "source_system_class", "source_valid_from", "source_recorded_at",
    "graph_ingested_at", "graph_updated_at", "extraction_run_id",
}


def _fmt(cypher: str, params: dict) -> str:
    return f"{' '.join(cypher.split())}\n    -- params: {params}"


def check_system_class_resolution(
    situations: list[Card], models_by_id: dict[str, ReferenceModelCard]
) -> dict[str, list[str]]:
    """Every `system_class` on a card MUST resolve to a `:System` node in its
    `stack_ref`. Returns {card_id: [unresolvable...]} — a non-empty result is a
    load error."""
    errors: dict[str, list[str]] = {}
    for card in situations:
        model = models_by_id.get(card.stack_ref)
        if model is None or not model.has_graph:
            continue
        graphed = model.system_classes
        refs = [("trigger.source", card.trigger_source.system_class)]
        refs += [("source_systems", s) for s in card.source_systems]
        for strat in card.strategies:
            refs += [(f"strategy {strat.id}", ap.system_class) for ap in strat.action_paths]
        missing = sorted({v for _, v in refs if v not in graphed})
        if missing:
            errors[card.id] = missing
    return errors


def check_provenance_assertions(
    situations: list[Card], models_by_id: dict[str, ReferenceModelCard]
) -> tuple[dict[str, list[str]], list[str]]:
    """the load-time assertions (assertion 4, tracked_transitions.retains == 1, is
    enforced in the parser). All are errors, not warnings.

      1. `source_system_class` on an extracted sample node must resolve to a
         `:System` node in the card's `stack_ref`.
      2. `source_valid_to` must be null/absent on a node whose label maps to an
         APPEND_ONLY `:DataObject` — closing it converts a compensating
         correction into an edit (§2.12).
      3. A sample node that presents as extracted (carries any provenance key)
         must carry the required minimum set (`_REQUIRED_PROVENANCE`). A node
         carrying none is a permitted stub (§2.10).

    Returns ({card_id: [errors]}, [info notes]).
    """
    errors: dict[str, list[str]] = {}
    notes: list[str] = []
    for card in situations:
        model = models_by_id.get(card.stack_ref)
        if not (model and model.has_graph):
            continue
        graphed = model.system_classes
        ws_by_name = model.write_semantics_by_object_name
        label_by_id = {e.id: e.label for e in card.entities}
        card_errs: list[str] = []
        stubs = 0
        for node_id, props in card.sample_instance.items():
            carried = {k for k in props if k in PROVENANCE_KEYS}
            label = label_by_id.get(node_id, "")
            if not carried:
                if label in EXTRACTED_NODE_LABELS:
                    stubs += 1
                continue
            # assertion 1
            ssc = props.get("source_system_class")
            if ssc is not None and graphed and ssc not in graphed:
                card_errs.append(f"{node_id}: source_system_class {ssc!r} does not resolve to a :System in {card.stack_ref}")
            # assertion 2
            norm = "".join(ch for ch in label.lower() if ch.isalnum())
            appendonly = any(
                norm and (norm in oname or oname.endswith(norm) or oname.startswith(norm)) and sem == "APPEND_ONLY"
                for oname, sem in ws_by_name.items()
            )
            if appendonly and props.get("source_valid_to") not in (None, "null"):
                card_errs.append(f"{node_id}: source_valid_to is set on an APPEND_ONLY object ({label}) — §2.12")
            # assertion 3
            missing = sorted(_REQUIRED_PROVENANCE - set(props))
            if missing:
                card_errs.append(f"{node_id}: presents as extracted but missing required provenance {missing}")
        if card_errs:
            errors[card.id] = card_errs
        if stubs:
            notes.append(f"{card.id}: {stubs} extracted sample node(s) carry no provenance (permitted stub, §2.10)")
    return errors, notes


def run(
    situations: list[Card],
    reference_models: list[ReferenceModelCard],
    *,
    keep: bool,
    skills: list[SkillDoc] | None = None,
) -> tuple[dict[str, int], list[str]]:
    stmts: list[tuple[str, dict]] = []
    if not keep:
        stmts.append(db.wipe())
    load_stmts, unresolved_writes = db.full_load_statements(situations, reference_models, skills)
    stmts += load_stmts

    counts = {"statements": len(stmts)}
    with db.driver() as drv:
        # One transaction for the whole wipe + rebuild.
        # Memgraph is snapshot-isolated: a concurrent MCP read sees either the
        # old committed graph or the new one, never the half-built state in
        # between — which is what made `get_stack_model` return an empty stack
        # with no error while a reload was in flight.
        with drv.session() as session:
            tx = session.begin_transaction()
            try:
                for cypher, params in stmts:
                    tx.run(cypher, **params)
                tx.commit()
            except BaseException:
                tx.rollback()
                raise
        with drv.session() as session:
            for label, key in [
                ("nodes", "MATCH (n) RETURN count(n) AS c"),
                ("relationships", "MATCH ()-[r]->() RETURN count(r) AS c"),
                ("situation_types", "MATCH (s:SituationType) RETURN count(s) AS c"),
                ("action_paths", "MATCH (a:ActionPath) RETURN count(a) AS c"),
                ("reference_models", "MATCH (m:ReferenceModel) RETURN count(m) AS c"),
                ("systems", "MATCH (s:System) RETURN count(s) AS c"),
                ("data_objects", "MATCH (o:DataObject) RETURN count(o) AS c"),
                ("interfaces", "MATCH (i:Interface) RETURN count(i) AS c"),
                ("blind_spots", "MATCH (b:BlindSpot) RETURN count(b) AS c"),
                ("detected_by", "MATCH ()-[r:DETECTED_BY]->() RETURN count(r) AS c"),
                ("acts_on", "MATCH ()-[r:ACTS_ON]->() RETURN count(r) AS c"),
                ("writes", "MATCH ()-[r:WRITES]->() RETURN count(r) AS c"),
                ("covers", "MATCH ()-[r:COVERS]->() RETURN count(r) AS c"),
                ("tracked_transitions", "MATCH (t:TrackedTransition) RETURN count(t) AS c"),
                ("append_only_objects",
                 "MATCH (o:DataObject {write_semantics: 'APPEND_ONLY'}) RETURN count(o) AS c"),
                ("skills", "MATCH (k:Skill) RETURN count(k) AS c"),
                ("has_skill", "MATCH ()-[r:HAS_SKILL]->() RETURN count(r) AS c"),
            ]:
                counts[label] = session.run(key).single()["c"]
    return counts, unresolved_writes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--keep", action="store_true", help="do not wipe the graph first")
    ap.add_argument("--include-solver", action="store_true")
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR,
                    help=f"skills/ directory (default {DEFAULT_SKILLS_DIR.name}/); pass a "
                         f"missing path to load no skills")
    ap.add_argument("--skip-provenance-check", action="store_true",
                    help="dev-only: run the load even if the provenance assertions fail")
    ap.add_argument("--dry-run", action="store_true", help="print Cypher, touch no database")
    args = ap.parse_args(argv)

    ds = parse_file(args.file)
    reference_models = ds.reference_models
    models_by_id = {m.id: m for m in reference_models}
    loaded = [c for c in ds.situations if args.include_solver or c.is_judgment]
    skipped = [c for c in ds.situations if c not in loaded]

    all_skills = parse_skills_dir(args.skills_dir)
    loaded_situation_ids = {c.id for c in loaded}
    skills = [
        s for s in all_skills
        if s.is_triage or s.situation_id in loaded_situation_ids
    ]
    orphan_skills = [
        s.name for s in all_skills
        if not s.is_triage and s.situation_id not in loaded_situation_ids
    ]

    print(f"Parsed {len(ds.situations)} situation cards + {len(ds.reference_models)} reference models "
          f"+ {len(all_skills)} skills")
    for m in reference_models:
        print(f"  model {m.id}  graph: {len(m.entity_refs)} nodes / {len(m.stack_edges)} edges")
    for c in loaded:
        print(f"  load  {c.id}  {c.name}")
    for c in skipped:
        print(f"  skip  {c.id}  ({c.qualifier_classification})")
    for s in skills:
        tgt = s.situation_id or "triage (cross-cutting)"
        print(f"  skill {s.name}  -> {tgt}")
    for name in orphan_skills:
        print(f"  note  skill {name} names a situation not being loaded — skipped")

    # Unresolvable system_class is a load error.
    res_errors = check_system_class_resolution(loaded, models_by_id)
    if res_errors:
        print("\nLOAD ERROR — unresolvable system_class on a graph-backed model:", file=sys.stderr)
        for cid, vals in res_errors.items():
            print(f"  {cid}: {vals}", file=sys.stderr)
        return 1

    # provenance / bitemporality assertions, all errors.
    prov_errors, prov_notes = check_provenance_assertions(loaded, models_by_id)
    for n in prov_notes:
        print(f"  note  {n}")
    if prov_errors:
        print("\nLOAD ERROR — provenance assertion(s) failed:", file=sys.stderr)
        for cid, errs in prov_errors.items():
            for e in errs:
                print(f"  {cid}: {e}", file=sys.stderr)
        if not args.skip_provenance_check:
            print("  (re-run with --skip-provenance-check to load anyway; dev only)", file=sys.stderr)
            return 1
        print("  --skip-provenance-check set: loading anyway", file=sys.stderr)

    if not loaded:
        print("Nothing to load.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n--- Cypher (dry run) ---")
        load_stmts, unresolved_writes = db.full_load_statements(loaded, reference_models, skills)
        stmts = ([] if args.keep else [db.wipe()]) + load_stmts
        for cypher, params in stmts:
            print(_fmt(cypher, params))
        print(f"\n{len(stmts)} statements. {len(unresolved_writes)} writes did not resolve to a DataObject.")
        return 0

    counts, unresolved_writes = run(loaded, reference_models, keep=args.keep, skills=skills)
    print(
        f"\nLoaded: {counts['nodes']} nodes, {counts['relationships']} relationships "
        f"({counts['statements']} statements).\n"
        f"  situation_types={counts['situation_types']} action_paths={counts['action_paths']} "
        f"reference_models={counts['reference_models']} "
        f"skills={counts['skills']} (has_skill={counts['has_skill']})\n"
        f"  stack: systems={counts['systems']} "
        f"data_objects={counts['data_objects']} (append_only={counts['append_only_objects']}) "
        f"interfaces={counts['interfaces']} blind_spots={counts['blind_spots']}\n"
        f"  situation->stack: detected_by={counts['detected_by']} acts_on={counts['acts_on']} "
        f"writes={counts['writes']} covers={counts['covers']} "
        f"tracked_transitions={counts['tracked_transitions']}"
    )
    if unresolved_writes:
        print(f"\n{len(unresolved_writes)} system_of_action `writes` values did not map to a DataObject "
              f"(kept as ActionPath.writes properties; no WRITES edge). Sample:")
        for w in unresolved_writes[:8]:
            print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
