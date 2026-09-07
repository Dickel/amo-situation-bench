# AG-01 — Situation Qualifier

Status: **BUILDABLE and built.** Every tool it calls is live on
`mcp.sooriah.com/amo/mcp`. 40 offline tests pass with no network and no model
spend.

Turns an unstructured description or an entity id into one of four verdicts.
Only the first leads anywhere else.

| Verdict | Meaning |
|---|---|
| `JUDGMENT_IN_BENCH` | A benched judgment situation. Hand off to the named skill and to AG-04 |
| `SOLVER` | Some engine already answers this. `solver_owner` names it |
| `UNDETECTABLE_HERE` | The situation is real; the systems needed to see it are not in this stack |
| `NOT_IN_BENCH` | Outside the bench. `boundary_explanation` says where the boundary falls |

`NOT_IN_BENCH` is not a failure. A bench that answers everything has no boundary,
and the boundary is the product.

---

## The two design decisions worth reviewing

**Sequencing is graph topology, not a prompt instruction.**

```
route ──┬── match  (entity id present)  ──┐
        └── screen (prose only)        ──┴── qualify ── detect_check ── verdict
```

The triage skill's central rule is an ordering constraint. A ReAct agent handed
four tools and told the order in a system prompt follows it most of the time,
and the failure is silent. Here `qualify` is on the only path to `verdict`, and
`detect_check` runs unconditionally — conditionally would mean the ABSENT check
depends on a value read from the payload it exists to validate. The model
chooses content at two nodes. It never chooses sequence.

**`get_strategies` is not bound at all.** The rule *never enumerate strategies
before qualifying* is enforced by the tool surface rather than by an
instruction, which is the stronger form — a sufficiently confident model
eventually calls a tool it has. `bench.py` raises `PermissionError` naming AG-04
as the owner.

## What the schema enforces that a prompt cannot

`QualifierResult` is a Pydantic model with a validator, because three documented
failure modes are only checkable against a structured field:

- **Claiming ABSENT without checking the instantiated stack.**
  `detectability_confirmed_against` must be `instantiated_stack` for any match
  reporting `ABSENT`, or construction fails. Since no customer stack exists yet,
  `is_instantiated()` returns `False` everywhere and AG-01 **downgrades ABSENT
  to DERIVED and says why**. This is the correct behaviour today and the field
  that makes it correct tomorrow.
- **Fabricating a situation id.** Ids are filtered against
  `list_situation_types` inside the screening node, before they can propagate.
- **Improvising strategies.** `verdict` is a closed enum and the model has no
  field to put strategies in.

`SOLVER` without `solver_owner`, and `NOT_IN_BENCH` with matches or without a
boundary explanation, are also rejected.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # only needed for the prose path

python -m ag01_situation_qualifier.run "What's happening with WO-4471?"
python -m ag01_situation_qualifier.run --offline "..."   # fixtures, no spend
python -m ag01_situation_qualifier.run --json "..."

python ag01_situation_qualifier/tests/test_offline.py    # 15 tests, no network
python -m ag01_situation_qualifier.capture_fixtures      # refresh from live bench
```

Langfuse tracing activates when `LANGFUSE_PUBLIC_KEY` is set and is silently off
otherwise, so this runs on a laptop with nothing configured.

## Sample output

```
VERDICT  JUDGMENT_IN_BENCH

Qualifies as judgment territory: SIT-AMO-001, SIT-AMO-004. Competent
practitioners given identical data would diverge with defensible reasoning.
Detectability was checked against the reference model only, so no ABSENT claim
is made here — that requires the customer's instantiated stack.

SIT-AMO-001 — Scarce common part contention
  classification   judgment
  detectability    DERIVED  (confirmed against reference_model)
  matched          PART-XR200, WO-4471, WO-4482
  hand off to      amo-part-contention

SIT-AMO-004 — Bottleneck slot contention under a committed sequence
  ...

tools called: match_situations(WO-4471) -> explain_qualifier(SIT-AMO-001)
              -> explain_qualifier(SIT-AMO-004) -> get_stack_model()
AG-01 qualifies only. Strategy enumeration is AG-04, after this verdict.
```

## Layout

| File | |
|---|---|
| `graph.py` | The LangGraph. Sequencing lives here as edges |
| `schema.py` | `QualifierResult` and its validator |
| `bench.py` | `LiveBench` (MCP over streamable HTTP) and `FixtureBench` (offline replay), one interface, plus the tool allowlist |
| `prompts.py` | The two prompts. No ordering instructions — there is nothing here to disobey |
| `run.py` | CLI with optional Langfuse tracing |
| `capture_fixtures.py` | Refresh fixtures from the live bench |
| `fixtures/amo.json` | Real captured payloads, all five cards |
| `tests/test_offline.py` | 15 tests, no network, no model calls |

## Known limits

- **The prose path is untested against a model.** `tests/test_offline.py` stubs
  the screening node, so what is verified is sequencing, the allowlist, the
  schema, and plant-dependent detectability. Screening quality needs the triage
  eval suite, which spends tokens and has not been run.
- **`UNDETECTABLE_HERE` and the `ABSENT`→`DERIVED` downgrade only fire with a
  plant.** Against the live server's reference model, AG-01 correctly declines
  to assert `ABSENT` at all — which is right, and untestable. `--plant PLANT-B`
  (offline) is what exercises those paths.
- **Fixtures go stale silently.** A bench reload that changes a payload leaves
  the offline tests green while live behaviour diverges. Re-run
  `capture_fixtures` after any reload.
- **SIT-AMO-002 and SIT-AMO-003 have no handoff skill** (only 4 skills exist).
  AG-01 qualifies them; it just has nothing to hand off to.
- **Entity-id detection is a regex** over the bench's id conventions. It is
  deliberately strict: a false positive sends a prose question down the match
  path and wastes a call; a false negative costs one screening step.
