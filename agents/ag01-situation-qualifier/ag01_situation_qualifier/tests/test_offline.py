"""Offline tests. No network, no model calls.

The graph is exercised with the fixture bench and the screening node stubbed,
so what is under test is the part that must never vary: sequencing, the tool
allowlist, and the verdict schema's refusal to accept an unsound shape.

The model-dependent behaviour (prose screening) is covered by evaluate.py,
which does spend tokens and is not run in CI by default.
"""
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ag01_situation_qualifier import FixtureBench, Verdict, ConfirmedAgainst
from ag01_situation_qualifier import graph as G
from ag01_situation_qualifier.schema import QualifierResult, SituationMatch
import pydantic

PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not cond else ""))


def stub_screen(ids):
    async def _s(state, *, bench):
        listing = await bench.call("list_situation_types")
        valid = {s["id"]: s["name"] for s in listing["situation_types"]}
        return {"candidates": [{"situation_id": i, "name": valid[i]} for i in ids],
                "notes": ["stubbed screen"]}
    return _s


async def run(question, screen_ids=None):
    bench = FixtureBench()
    real = G.screen
    if screen_ids is not None:
        G.screen = stub_screen(screen_ids)
    try:
        return await G.qualify_question(question, bench), bench
    finally:
        G.screen = real


async def main():
    print("\n1. Sequencing is topology")
    r, b = await run("What's happening with WO-4471?")
    order = [c.split("(")[0] for c in b.calls]
    check("match_situations runs before explain_qualifier",
          order.index("match_situations") < order.index("explain_qualifier"), order)
    check("get_stack_model always runs", "get_stack_model" in order, order)
    check("explain_qualifier runs before get_stack_model",
          order.index("explain_qualifier") < order.index("get_stack_model"), order)

    print("\n2. Tool allowlist is enforced at the transport")
    try:
        await FixtureBench().call("get_strategies", situation_id="SIT-AMO-001")
        check("get_strategies is refused", False, "call succeeded")
    except PermissionError as e:
        check("get_strategies is refused", "AG-04" in str(e))

    print("\n3. Both cards on a shared entity are returned (open item A3)")
    ids = {m.situation_id for m in r.matches}
    check("WO-4471 -> SIT-AMO-001 and SIT-AMO-004", ids == {"SIT-AMO-001", "SIT-AMO-004"}, ids)

    print("\n4. ABSENT is not asserted against the reference model")
    check("confirmed_against is reference_model",
          r.detectability_confirmed_against is ConfirmedAgainst.REFERENCE_MODEL)
    a004 = next(m for m in r.matches if m.situation_id == "SIT-AMO-004")
    check("SIT-AMO-004 downgraded ABSENT -> DERIVED", a004.detectability == "DERIVED",
          a004.detectability)
    check("reasoning says why no ABSENT claim", "ABSENT claim is made" in r.reasoning)

    print("\n5. Schema rejects an unsound verdict")
    try:
        QualifierResult(verdict=Verdict.JUDGMENT_IN_BENCH, reasoning="x",
            matches=[SituationMatch(situation_id="SIT-AMO-004", name="n",
                classification="judgment", detectability="ABSENT", trigger_condition="t")],
            detectability_confirmed_against=ConfirmedAgainst.REFERENCE_MODEL)
        check("ABSENT + reference_model is rejected", False, "accepted")
    except pydantic.ValidationError as e:
        check("ABSENT + reference_model is rejected", "instantiated stack" in str(e))
    try:
        QualifierResult(verdict=Verdict.SOLVER, reasoning="x")
        check("SOLVER without solver_owner is rejected", False, "accepted")
    except pydantic.ValidationError:
        check("SOLVER without solver_owner is rejected", True)
    try:
        QualifierResult(verdict=Verdict.NOT_IN_BENCH, reasoning="x")
        check("NOT_IN_BENCH without boundary_explanation is rejected", False, "accepted")
    except pydantic.ValidationError:
        check("NOT_IN_BENCH without boundary_explanation is rejected", True)

    print("\n6. Unknown entity -> NOT_IN_BENCH, no fabricated matches")
    r2, b2 = await run("What about WO-9999?")
    check("verdict is NOT_IN_BENCH", r2.verdict is Verdict.NOT_IN_BENCH, r2.verdict)
    check("no matches carried", r2.matches == [])

    print("\n7. Prose with no catalogue hit -> NOT_IN_BENCH")
    r3, _ = await run("Night shift clocks against the wrong work order.", screen_ids=[])
    check("verdict is NOT_IN_BENCH", r3.verdict is Verdict.NOT_IN_BENCH, r3.verdict)

    print("\n8. Handoff target is named, not loaded")
    check("SIT-AMO-001 -> amo-part-contention",
          next(m for m in r.matches if m.situation_id == "SIT-AMO-001").handoff_skill
          == "amo-part-contention")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0

sys.exit(asyncio.run(main()))
