# loader

Turns `data/amo-situations.md` into a Memgraph graph.

```bash
pip install -r loader/requirements.txt
MEMGRAPH_URI=bolt://localhost:7687 python -m loader.load
MEMGRAPH_URI=bolt://localhost:7687 python -m loader.validate
```

## What each file does

| File | |
|---|---|
| `cards.py` | Markdown → typed `Card` / `ReferenceModelCard` dataclasses. Pure Python, no DB. Scans every ```yaml block, classifies by its `id` + `card_type`. Enforces the schema: every trigger pattern domain-scoped, `retains == 1` on a tracked transition, every `:DataObject` declares `write_semantics`. |
| `skills.py` | `skills/<name>/SKILL.md` frontmatter → `SkillDoc`. |
| `db.py` | Cypher generation. `system_of_action` → `ActionPath` nodes; `SENDS` → reified `:Interface`; skills → `:Skill` nodes. |
| `load.py` | Wipe + rebuild, **in one transaction** — a concurrent reader never sees a half-built graph. Runs the four §8 provenance assertions (all errors) and the `system_class` resolution check before writing. |
| `validate.py` | Runs each card's raw `trigger.pattern` against its own `sample_instance`, in isolation, and reports `OK` / `NO_MATCH` / `ERROR`. |

## The reference model as a graph

`MODEL-AMO-PLANT-IT` carries `entity_refs` / `edges`: ~40 nodes (`System` ×9,
`DataObject` ×18, `BusinessProcess` ×8, `Standard` ×5) and typed edges. A
situation card's `system_class` values resolve against it — an unresolvable one
is a load error. Loading a card also creates `DETECTED_BY` / `EVIDENCED_BY` /
`ACTS_ON` / `COVERS` and strict-match `WRITES` edges.

`BETWEEN` edges in the model's `edges:` list are skipped — they reference
BlindSpot ids that `entity_refs` never declares (a known source inconsistency);
BlindSpots load from `known_blind_spots:` instead.

## Provenance / bitemporality

Extracted `sample_instance` nodes carry a provenance property set (`source_*`
valid time, `graph_*` transaction time, `extraction_run_id`). A field that fires
on a *change* declares a `tracked_transition` (`<field>_prior` +
`<field>_changed_at`, `retains: 1`). A data object declares `write_semantics`
(`APPEND_ONLY` | `UPDATABLE`), with `default_write_semantics` on the system as
fallback. The four load-time assertions:

1. `source_system_class` on an extracted node resolves to a `:System`.
2. No `source_valid_to` on a node whose `:DataObject` is `APPEND_ONLY`.
3. `extraction_run_id` present on any node that presents as extracted (a node
   carrying no provenance is a permitted stub).
4. `tracked_transitions[].retains == 1` (parser).

`--skip-provenance-check` bypasses 1–3 for local iteration only.

## Known findings, flagged not fixed

- `SIT-AMO-005` compares a fixed sample against `date()`, so whether its trigger
  fires depends on the wall-clock day. `loader.validate` shows it `NO_MATCH`
  most days. Candidate fix: an `as_of` field. Card-owner call.
- `SIT-AMO-005` also should sum the confirmed quantity over unreversed
  `:Confirmation` nodes (§2.12); the single-node sample can't exercise that.
- `write_semantics` is `APPEND_ONLY` on 6 of 18 data objects. Candidates for more
  (`committed sequence`, `supplier promise date`, `planned order`) are a
  card-owner call.
