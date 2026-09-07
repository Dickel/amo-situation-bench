"""Verdict coverage across the stack instantiation set.

test_offline.py verifies sequencing, the tool allowlist and the schema against
the reference model. This file verifies the thing the reference model cannot
show: that detectability depends on which plant you are standing in.

All three plants are synthetic and live in instances/. No network, no model.
"""
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ag01_situation_qualifier import FixtureBench, Verdict, ConfirmedAgainst
from ag01_situation_qualifier import graph as G

PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not cond else ""))

def stub(ids):
    async def _s(state, *, bench):
        listing = await bench.call("list_situation_types")
        valid = {s["id"]: s["name"] for s in listing["situation_types"]}
        return {"candidates": [{"situation_id": i, "name": valid[i]} for i in ids],
                "notes": []}
    return _s

async def ask(ids, plant):
    bench = FixtureBench(plant=plant)
    real = G.screen
    G.screen = stub(ids)
    try:
        return await G.qualify_question("(stubbed)", bench)
    finally:
        G.screen = real

def det(r, sid):
    return next((m.detectability for m in r.matches if m.situation_id == sid), None)

async def main():
    print("\n1. PLANT-A — full stack: ABSENT is assertable")
    a = await ask(["SIT-AMO-003", "SIT-AMO-004", "SIT-AMO-005"], "PLANT-A")
    check("verdict JUDGMENT_IN_BENCH", a.verdict is Verdict.JUDGMENT_IN_BENCH, a.verdict)
    check("confirmed against instantiated stack",
          a.detectability_confirmed_against is ConfirmedAgainst.INSTANTIATED_STACK)
    check("SIT-AMO-003 stays ABSENT", det(a, "SIT-AMO-003") == "ABSENT", det(a, "SIT-AMO-003"))
    check("SIT-AMO-004 stays ABSENT", det(a, "SIT-AMO-004") == "ABSENT", det(a, "SIT-AMO-004"))
    check("SIT-AMO-005 stays ABSENT", det(a, "SIT-AMO-005") == "ABSENT", det(a, "SIT-AMO-005"))

    print("\n2. PLANT-B — no APS: UNDETECTABLE_HERE is reachable")
    b = await ask(["SIT-AMO-004"], "PLANT-B")
    check("verdict UNDETECTABLE_HERE", b.verdict is Verdict.UNDETECTABLE_HERE, b.verdict)
    miss = b.matches[0].missing_systems
    check("APS named as missing", "APS" in miss, miss)

    print("\n3. PLANT-B — bespoke integration: ABSENT must NOT be claimed")
    b3 = await ask(["SIT-AMO-003"], "PLANT-B")
    check("verdict JUDGMENT_IN_BENCH", b3.verdict is Verdict.JUDGMENT_IN_BENCH, b3.verdict)
    check("SIT-AMO-003 downgraded to DERIVED", det(b3, "SIT-AMO-003") == "DERIVED",
          det(b3, "SIT-AMO-003"))
    b5 = await ask(["SIT-AMO-005"], "PLANT-B")
    check("SIT-AMO-005 still ABSENT at same plant", det(b5, "SIT-AMO-005") == "ABSENT",
          det(b5, "SIT-AMO-005"))

    print("\n4. PLANT-C — no PLM: a different reason for the same verdict")
    c = await ask(["SIT-AMO-003"], "PLANT-C")
    check("verdict UNDETECTABLE_HERE", c.verdict is Verdict.UNDETECTABLE_HERE, c.verdict)
    check("PLM_ECM named as missing", "PLM_ECM" in c.matches[0].missing_systems,
          c.matches[0].missing_systems)
    c4 = await ask(["SIT-AMO-004"], "PLANT-C")
    check("SIT-AMO-004 ABSENT here (APS present)", det(c4, "SIT-AMO-004") == "ABSENT",
          det(c4, "SIT-AMO-004"))

    print("\n5. The same card gives three different answers across three plants")
    answers = {}
    for p in ("PLANT-A", "PLANT-B", "PLANT-C"):
        r = await ask(["SIT-AMO-003"], p)
        answers[p] = (r.verdict.value, det(r, "SIT-AMO-003"))
    print(f"        SIT-AMO-003: {answers}")
    check("three distinct outcomes", len(set(answers.values())) == 3, answers)

    print("\n6. No plant selected -> reference model -> no ABSENT claim")
    n = await ask(["SIT-AMO-004"], None)
    check("confirmed against reference_model",
          n.detectability_confirmed_against is ConfirmedAgainst.REFERENCE_MODEL)
    check("ABSENT downgraded", det(n, "SIT-AMO-004") == "DERIVED", det(n, "SIT-AMO-004"))

    print("\n7. Mixed result must not hide the detectable card")
    m = await ask(["SIT-AMO-001", "SIT-AMO-004"], "PLANT-B")
    check("verdict follows the detectable card",
          m.verdict is Verdict.JUDGMENT_IN_BENCH, m.verdict)
    check("both cards still reported", len(m.matches) == 2, len(m.matches))
    check("undetectable one names its missing system",
          "APS" in next(x for x in m.matches if x.situation_id == "SIT-AMO-004").missing_systems)
    check("reasoning flags the undetectable one", "not detectable in this stack" in m.reasoning)

    print("\n8. A situation id is a question about a card, not an instance")
    from ag01_situation_qualifier import FixtureBench as FB
    from ag01_situation_qualifier.graph import qualify_question
    n = await qualify_question("Is SIT-AMO-003 live here?", FB(plant="PLANT-C"))
    check("named card routes to the card, not match_situations",
          "match_situations" not in " ".join(n.tool_calls), n.tool_calls)
    check("verdict UNDETECTABLE_HERE at PLANT-C", n.verdict is Verdict.UNDETECTABLE_HERE, n.verdict)
    a8 = await qualify_question("Is SIT-AMO-003 live here?", FB(plant="PLANT-A"))
    check("verdict JUDGMENT_IN_BENCH at PLANT-A", a8.verdict is Verdict.JUDGMENT_IN_BENCH, a8.verdict)
    u = await qualify_question("What about SIT-AMO-099?", FB(plant="PLANT-A"))
    check("unknown card id -> NOT_IN_BENCH, not an error",
          u.verdict is Verdict.NOT_IN_BENCH, u.verdict)
    check("unknown id named in reasoning", "SIT-AMO-099" in u.reasoning)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0

sys.exit(asyncio.run(main()))
