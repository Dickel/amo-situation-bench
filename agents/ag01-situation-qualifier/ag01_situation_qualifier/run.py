"""AG-01 CLI.

    python -m ag01_situation_qualifier.run "What's happening with WO-4471?"
    python -m ag01_situation_qualifier.run --offline "..."      # fixtures, no spend
    python -m ag01_situation_qualifier.run --json "..."

Langfuse tracing is on when LANGFUSE_PUBLIC_KEY is set and silently off when it
is not, so the agent runs on a laptop with nothing configured.
"""
from __future__ import annotations

import argparse, asyncio, json, os, sys

from .bench import FixtureBench, LiveBench
from .graph import qualify_question
from .schema import QualifierResult, Verdict


def _tracer():
    """Langfuse v4: start_as_current_observation as a span wrapper, then flush."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse import get_client
        return get_client()
    except Exception as e:  # noqa: BLE001
        print(f"[langfuse disabled: {e}]", file=sys.stderr)
        return None


def render(r: QualifierResult) -> str:
    L = [f"VERDICT  {r.verdict.value}", "", r.reasoning, ""]
    if r.verdict is Verdict.SOLVER:
        L += [f"ALREADY ANSWERED BY  {r.solver_owner}", ""]
    for m in r.matches:
        L.append(f"{m.situation_id} — {m.name}")
        L.append(f"  classification   {m.classification}")
        L.append(f"  detectability    {m.detectability}"
                 f"  (confirmed against {r.detectability_confirmed_against.value})")
        if m.matched_instances:
            L.append(f"  matched          {', '.join(m.matched_instances)}")
        if m.missing_systems:
            L.append(f"  MISSING SYSTEMS  {', '.join(m.missing_systems)}")
        if m.solver_boundary:
            L.append(f"  already solved   {m.solver_boundary[:160]}…")
        if m.handoff_skill:
            L.append(f"  hand off to      {m.handoff_skill}")
        L.append("")
    if r.boundary_explanation:
        L += ["WHERE THE BOUNDARY FALLS", r.boundary_explanation, ""]
    L.append(f"tools called: {' -> '.join(r.tool_calls)}")
    L.append("AG-01 qualifies only. Strategy enumeration is AG-04, after this verdict.")
    return "\n".join(L)


async def main() -> int:
    ap = argparse.ArgumentParser(prog="ag01")
    ap.add_argument("question")
    ap.add_argument("--offline", action="store_true", help="use captured fixtures")
    ap.add_argument("--plant", help="stack instantiation: PLANT-A | PLANT-B | PLANT-C. "
                                    "Without it, detectability resolves against the "
                                    "reference model and no ABSENT claim is made.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()

    bench = FixtureBench(plant=a.plant) if a.offline else LiveBench()
    if not a.offline and a.plant:
        print("[--plant applies to --offline only; live stack comes from the server]",
              file=sys.stderr)
    lf = _tracer()
    if lf:
        with lf.start_as_current_observation(as_type="span", name="AG-01") as span:
            r = await qualify_question(a.question, bench)
            span.update(input={"question": a.question},
                        output=r.model_dump(mode="json"),
                        metadata={"agent": "AG-01", "tool_calls": r.tool_calls})
        lf.flush()
    else:
        r = await qualify_question(a.question, bench)

    print(json.dumps(r.model_dump(mode="json"), indent=2) if a.as_json else render(r))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
