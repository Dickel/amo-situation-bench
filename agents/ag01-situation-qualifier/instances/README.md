# Stack instantiation set — v0.1

Three synthetic plants. Each is an instance of `MODEL-AMO-PLANT-IT` describing
which systems a specific site actually runs.

They exist because **detectability is a property of a plant, not of a card.**
`SIT-AMO-003` is `ABSENT` in the reference model, and that value is only true
somewhere. Without an instantiation the bench can state the reference claim and
can never check it, and AG-01 correctly refuses to assert `ABSENT` at all —
which is right, and untestable.

No customer data. All three are invented, consistent with the bench rule.

| | Plant A | Plant B | Plant C |
|---|---|---|---|
| Shape | full stack | no APS, one bespoke integration | no PLM/ECM |
| Systems | 9 | 6 | 7 |
| Live blind spots | 3 | 1 | 2 |
| Makes reachable | `ABSENT` on all three cards | `UNDETECTABLE_HERE`, and the ABSENT→DERIVED downgrade | `UNDETECTABLE_HERE` for a structurally different reason |

## Why three, and why these three

**Plant A** is the reference landscape actually instantiated. It is the only
plant where an `ABSENT` claim is defensible on all three cards, so it is the
only one where the strongest form of the value claim can be tested rather than
asserted.

**Plant B** has no APS — sequencing is a planner with a spreadsheet, which is the
common mid-market shape. `SIT-AMO-004` becomes `UNDETECTABLE_HERE`, and for a
reason worth stating precisely: it is not that nothing arbitrates the solver's
output, it is that there is no solver output. That is a stronger finding than an
unowned comparison and should be reported as one.

Plant B also carries a **bespoke PLM→ERP effectivity check** built in-house.
`SIT-AMO-003` is therefore `DERIVED` here, not `ABSENT`. This is the plant that
disciplines the pitch: one of the three headline blind spots does not exist, and
claiming it would be falsified in the room by the person who built the
integration.

**Plant C** breaks `SIT-AMO-003` for a different reason. At Plant B a system was
missing; here the *object* is not systematised — effectivity exists, in a
controlled spreadsheet and an email thread, but nowhere queryable. The
remediation differs (connect a source versus build a comparison) and conflating
them misprices the work.

## Blind spots are derived, not authored

Each plant declares what it runs. It does not declare its blind spots. Those are
computed by diffing the instantiation against the reference model:

- both systems present, no bespoke comparison → **live**
- both present, bespoke comparison exists → **closed**, with the detectability
  it degrades to
- one or both absent → **unreachable**, and the covering card is
  `UNDETECTABLE_HERE`

Closed and unreachable are different facts and produce different verdicts.
Collapsing them is the mistake this structure exists to prevent.

Each card carries an `expected` block, which makes the derivation checkable
rather than merely runnable.

```bash
python -m instances.derive              # all plants
python -m instances.derive --check      # exit 1 on any oracle mismatch
```

## Using them with AG-01

```bash
python -m ag01_situation_qualifier.run --offline --plant PLANT-B "..."
python agents/ag01_situation_qualifier/tests/test_plants.py    # 20 tests
```

Without `--plant`, detectability resolves against the reference model and AG-01
makes no `ABSENT` claim. That is the correct default and the reason the set is
needed.

## What this set caught

Building it found three defects that the reference model alone could not
surface:

1. **`include_cypher: false` strips payload arrays** from `get_stack_model` —
   `systems`, `interfaces` and `blind_spots[].systems` all return empty. AG-01
   was reading an empty stack and silently disabling every detectability check.
   Server-side bug; AG-01 now requests the full payload and drops the `cypher`
   key itself.
2. **The graph never consumed `closed_blind_spots`**, so Plant B's bespoke
   integration did not downgrade `SIT-AMO-003`. The over-claim guard existed and
   was unreachable.
3. **A mixed result reported `UNDETECTABLE_HERE` for everything**, hiding the
   cards that do fire. WO-4471 at Plant B triggers `SIT-AMO-001` (detectable) and
   `SIT-AMO-004` (not); the verdict now follows the detectable half and the rest
   stay in `matches` with their `missing_systems`.

## Status

`[PROPOSED]` — the plants are synthetic and their `expected` blocks are authored
judgments about what the derivation should produce, not observations. They are
internally consistent and derive cleanly. They have not been checked against a
real site.
