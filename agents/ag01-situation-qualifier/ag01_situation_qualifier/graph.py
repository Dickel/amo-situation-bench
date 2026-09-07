"""AG-01 Situation Qualifier — LangGraph implementation.

Design note, and the reason this is a graph rather than a tool-calling loop.

The triage skill's central rule is an ordering constraint: never enumerate
strategies before qualifying, and never assert ABSENT before checking the
instantiated stack. A ReAct agent handed four tools and told the order in a
system prompt will follow it most of the time. Most of the time is not a
guarantee, and the failure is silent.

So the order is the graph:

    route ──┬── match  (entity id present)  ──┐
            └── screen (prose only)        ──┴── qualify ── detect_check ── verdict

The model chooses *content* at two nodes (screen, and the solver/judgment read
in verdict). It never chooses *sequence*. And `get_strategies` is not bound at
all, so the strategy-enumeration failure is unreachable rather than discouraged.
"""

from __future__ import annotations

import os
import re
from typing import Annotated, Any, Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, StateGraph

from .bench import Bench, is_instantiated, systems_in_stack
from .prompts import SCREEN_PROMPT, VERDICT_PROMPT
from .schema import (
    HANDOFF_SKILLS,
    ConfirmedAgainst,
    QualifierResult,
    SituationMatch,
    Verdict,
)

MODEL = os.getenv("AG01_MODEL", "claude-sonnet-4-5-20250929")

# Entity ids the bench uses. Deliberately narrow: a false positive here sends a
# prose question down the match path, where it returns found=False and wastes a
# call. A false negative costs one extra screening step. The asymmetry favours
# being strict.
ENTITY_ID = re.compile(r"\b(WO|PO|POL|PART|WC|OP|CUST|SUP|ECO)-[A-Z0-9][A-Z0-9-]*\b")

# A situation id is not an instance. Asking "is SIT-AMO-003 live here?" is a
# question about a card, not about a work order, and routing it through
# match_situations returns NOT_IN_BENCH for a card that plainly exists.
SITUATION_ID = re.compile(r"\bSIT-AMO-\d{3}\b")


class State(TypedDict, total=False):
    question: str
    entity_ids: list[str]
    situation_ids: list[str]
    candidates: list[dict]          # [{situation_id, name, matched_instances?}]
    qualifiers: dict[str, dict]     # situation_id -> explain_qualifier payload
    stack: dict
    known_ids: set[str]
    result: QualifierResult
    notes: Annotated[list[str], lambda a, b: a + b]


def _llm(**kw: Any) -> ChatAnthropic:
    kw.setdefault("max_tokens", 2000)
    return ChatAnthropic(model=MODEL, temperature=0, **kw)


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #

async def route(state: State) -> State:
    # finditer, not findall: the pattern has a group, and findall would return
    # the group ("WO") rather than the whole id.
    ids = sorted({m.group(0) for m in ENTITY_ID.finditer(state["question"])})
    sids = sorted({m.group(0) for m in SITUATION_ID.finditer(state["question"])})
    return {"entity_ids": ids, "situation_ids": sids}


def _route_edge(state: State) -> Literal["named", "match", "screen"]:
    """Three ways in, and they are not interchangeable.

    A named situation id is a question about a card. An entity id is a question
    about an instance, answered by the graph. Prose is answered by screening.
    """
    if state.get("situation_ids"):
        return "named"
    return "match" if state.get("entity_ids") else "screen"


async def named(state: State, *, bench: Bench) -> State:
    """Direct card lookup. Ids are validated against the catalogue first, so a
    plausible-looking but non-existent id is reported as such rather than
    producing a tool error."""
    listing = await bench.call("list_situation_types")
    valid = {s["id"]: s["name"] for s in listing["situation_types"]}
    good = [i for i in state["situation_ids"] if i in valid]
    unknown = [i for i in state["situation_ids"] if i not in valid]
    note = f"named card lookup: {good or 'none valid'}"
    if unknown:
        note += f"; not in the catalogue: {', '.join(unknown)}"
    return {
        "candidates": [{"situation_id": i, "name": valid[i]} for i in good],
        "notes": [note],
    }


async def match(state: State, *, bench: Bench) -> State:
    """Graph-grounded path. The bench decides what fires; the model does not."""
    candidates: list[dict] = []
    seen: set[str] = set()
    for eid in state["entity_ids"]:
        res = await bench.call("match_situations", entity_id=eid)
        if not res.get("found"):
            continue
        for m in res.get("matches", []):
            if m["situation_id"] not in seen:
                seen.add(m["situation_id"])
                candidates.append(m)
    note = (
        f"match_situations returned {len(candidates)} candidate(s) for "
        f"{', '.join(state['entity_ids'])}"
        if candidates
        else f"no entity in the graph matched {', '.join(state['entity_ids'])}"
    )
    return {"candidates": candidates, "notes": [note]}


async def screen(state: State, *, bench: Bench) -> State:
    """Prose path. The model shortlists against the catalogue and may return
    nothing — which is the NOT_IN_BENCH verdict and a valid outcome."""
    listing = await bench.call("list_situation_types")
    catalogue = "\n".join(
        f"- {s['id']}: {s['name']}\n  fires when: {s['trigger_condition']}"
        for s in listing["situation_types"]
    )
    resp = await _llm().ainvoke(
        SCREEN_PROMPT.format(catalogue=catalogue, question=state["question"])
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    valid = {s["id"]: s["name"] for s in listing["situation_types"]}
    # Only ids the catalogue actually contains survive. A hallucinated id is
    # dropped here rather than caught later.
    picked = [i for i in re.findall(r"SIT-AMO-\d{3}", text) if i in valid]
    candidates = [
        {"situation_id": i, "name": valid[i]} for i in dict.fromkeys(picked)
    ]
    return {
        "candidates": candidates,
        "notes": [f"screened prose against catalogue -> {picked or 'no match'}"],
    }


async def qualify(state: State, *, bench: Bench) -> State:
    """Mandatory. Runs on every candidate before anything downstream sees it."""
    quals: dict[str, dict] = {}
    for c in state.get("candidates", []):
        sid = c["situation_id"]
        quals[sid] = await bench.call("explain_qualifier", situation_id=sid)
    return {"qualifiers": quals, "notes": [f"qualified {len(quals)} candidate(s)"]}


async def detect_check(state: State, *, bench: Bench) -> State:
    """Always runs, even when no candidate is ABSENT.

    Running it conditionally would mean the ABSENT check depends on a value read
    from the very payload it is meant to validate. Cheap call, unconditional.
    """
    stack = await bench.call("get_stack_model")
    kind = (
        "instantiated customer stack"
        if is_instantiated(stack)
        else "reference model only — ABSENT cannot be asserted"
    )
    return {"stack": stack, "notes": [f"stack model: {kind}"]}


async def verdict(state: State) -> State:
    quals = state.get("qualifiers", {})
    stack = state.get("stack", {})
    present = systems_in_stack(stack)
    instantiated = is_instantiated(stack)

    # A bespoke comparison at this plant closes a blind spot the reference model
    # says is open. The card still qualifies -- the judgment content is
    # unchanged -- but its detection claim weakens from ABSENT to whatever the
    # instantiation says. The card-to-blind-spot mapping comes from the stack
    # payload's covered_by, not from a table here, so it cannot drift.
    closed_for: dict[str, dict] = {}
    for bs in stack.get("closed_blind_spots") or []:
        for sid in bs.get("covered_by") or []:
            closed_for[sid] = bs

    if not quals:
        result = QualifierResult(
            verdict=Verdict.NOT_IN_BENCH,
            reasoning=(
                "No situation type in the AMO bench matches this. "
                + (
                    f"The situation ids given ({', '.join(state['situation_ids'])}) "
                    "are not in the AMO catalogue."
                    if state.get("situation_ids")
                    else f"The entity ids given ({', '.join(state['entity_ids'])}) are "
                    "not in the graph, or trigger no card."
                    if state.get("entity_ids")
                    else "The description does not match any card's trigger condition."
                )
            ),
            boundary_explanation=await _boundary(state),
            detectability_confirmed_against=(
                ConfirmedAgainst.INSTANTIATED_STACK
                if instantiated
                else ConfirmedAgainst.REFERENCE_MODEL
            ),
        )
        return {"result": result}

    matches: list[SituationMatch] = []
    for sid, q in quals.items():
        required = {q.get("trigger_source_system_class")} - {None}
        # A note like "PLM holds X, ERP holds Y" names the systems the ABSENT
        # claim rests on; pull them so missing_systems is real rather than
        # inferred from the trigger source alone.
        note = q.get("detectability_note") or ""
        required |= {t for t in re.findall(r"\b(ERP|MES|APS|PLM|QMS|IBP)\b", note)}
        required = {"PLM_ECM" if r == "PLM" else r for r in required}
        missing = sorted(required - present) if present else []

        detectability = q["detectability"]
        downgrade_note = None
        if sid in closed_for and detectability == "ABSENT":
            entry = closed_for[sid]
            detectability = entry.get("resulting_detectability", "DERIVED")
            downgrade_note = entry.get("closed_by")

        matches.append(
            SituationMatch(
                situation_id=sid,
                name=q["name"],
                classification=q["classification"],
                detectability=detectability,
                trigger_condition=q["trigger_condition"],
                solver_boundary=q.get("solver_boundary"),
                rationale=(
                    f"{q.get('rationale')} "
                    f"[Detection downgraded at this plant: {downgrade_note}]"
                    if downgrade_note
                    else q.get("rationale")
                ),
                matched_instances=next(
                    (
                        c.get("matched_instances", [])
                        for c in state.get("candidates", [])
                        if c["situation_id"] == sid
                    ),
                    [],
                ),
                required_systems=sorted(required),
                missing_systems=missing,
                handoff_skill=HANDOFF_SKILLS.get(sid),
            )
        )

    confirmed = (
        ConfirmedAgainst.INSTANTIATED_STACK
        if instantiated
        else ConfirmedAgainst.REFERENCE_MODEL
    )

    solver = [m for m in matches if m.classification == "solver"]
    judgment = [m for m in matches if m.classification == "judgment"]

    if solver and not judgment:
        result = QualifierResult(
            verdict=Verdict.SOLVER,
            reasoning=solver[0].solver_boundary or "Already solved by an existing engine.",
            matches=solver,
            solver_owner=_solver_owner(solver[0]),
            detectability_confirmed_against=confirmed,
        )
    elif judgment and all(m.missing_systems for m in judgment):
        result = QualifierResult(
            verdict=Verdict.UNDETECTABLE_HERE,
            reasoning=(
                "The situation is real and benched, but the systems it must be "
                "detected across are not present in this stack: "
                + ", ".join(
                    f"{m.situation_id} needs {', '.join(m.missing_systems)}"
                    for m in judgment
                )
                + "."
            ),
            matches=judgment,
            detectability_confirmed_against=confirmed,
        )
    else:
        # An ABSENT card cannot be reported as JUDGMENT_IN_BENCH against the
        # reference model — the schema validator rejects it. Downgrade the claim
        # rather than the verdict: report it as DERIVED-at-best and say why.
        if confirmed is not ConfirmedAgainst.INSTANTIATED_STACK:
            for m in judgment:
                if m.detectability == "ABSENT":
                    m.detectability = "DERIVED"
                    m.missing_systems = []
        # Mixed case: some cards detectable here, some not. Reporting the whole
        # result as UNDETECTABLE_HERE would hide the ones that do fire, which is
        # the more useful half of the answer. Verdict follows the detectable
        # cards; the rest stay in matches carrying their missing_systems.
        detectable = [m for m in judgment if not m.missing_systems]
        result = QualifierResult(
            verdict=Verdict.JUDGMENT_IN_BENCH,
            reasoning=_judgment_reasoning(detectable, confirmed)
            + (
                "  Also matched but not detectable in this stack: "
                + ", ".join(
                    f"{m.situation_id} (needs {', '.join(m.missing_systems)})"
                    for m in judgment
                    if m.missing_systems
                )
                + "."
                if any(m.missing_systems for m in judgment)
                else ""
            ),
            matches=judgment,
            detectability_confirmed_against=confirmed,
        )
    return {"result": result}


def _solver_owner(m: SituationMatch) -> str:
    b = (m.solver_boundary or "").upper()
    for engine in ("MRP", "APS", "CRP", "RCCP", "MES"):
        if engine in b:
            return engine
    return m.required_systems[0] if m.required_systems else "an existing engine"


def _judgment_reasoning(ms: list[SituationMatch], c: ConfirmedAgainst) -> str:
    ids = ", ".join(m.situation_id for m in ms)
    base = (
        f"Qualifies as judgment territory: {ids}. Competent practitioners given "
        "identical data would diverge with defensible reasoning."
    )
    downgraded = [m.situation_id for m in ms if "[Detection downgraded" in (m.rationale or "")]
    if downgraded:
        base += (
            f" Detection for {', '.join(downgraded)} is weaker here than the "
            "reference model implies: this plant already owns the comparison."
        )
    if c is not ConfirmedAgainst.INSTANTIATED_STACK:
        base += (
            " Detectability was checked against the reference model only, so no "
            "ABSENT claim is made here — that requires the customer's instantiated "
            "stack."
        )
    return base


async def _boundary(state: State) -> str:
    """Explain where the bench boundary falls.

    Deterministic by default. The model only enriches it, and only when a key is
    configured -- a NOT_IN_BENCH verdict must not fail because the enrichment
    call did. Saying "this is outside the bench" is the load-bearing part and it
    does not need a model to say it.
    """
    base = (
        "This is outside the AMO situation bench. The bench covers judgment-territory "
        "situations -- ones where competent practitioners given identical data would "
        "diverge with defensible reasoning -- across material contention, supplier "
        "slips, engineering change disposition, bottleneck arbitration and yield "
        "shortfall. A problem that falls outside is not necessarily unimportant; it "
        "is either solved by an existing engine, or a data-quality or process issue "
        "rather than a decision with competing defensible answers."
    )
    if not os.getenv("ANTHROPIC_API_KEY"):
        return base
    try:
        resp = await _llm(max_tokens=400).ainvoke(
            VERDICT_PROMPT.format(question=state["question"])
        )
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return text.strip() or base
    except Exception:  # noqa: BLE001 -- enrichment is optional by design
        return base


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def build(bench: Bench):
    """Compile AG-01. `bench` is injected so the same graph runs against the
    live MCP server or the offline fixtures with no code change."""

    async def _match(s: State) -> State:
        return await match(s, bench=bench)

    async def _screen(s: State) -> State:
        return await screen(s, bench=bench)

    async def _qualify(s: State) -> State:
        return await qualify(s, bench=bench)

    async def _detect(s: State) -> State:
        return await detect_check(s, bench=bench)

    g = StateGraph(State)
    async def _named(s: State) -> State:
        return await named(s, bench=bench)

    g.add_node("route", route)
    g.add_node("named", _named)
    g.add_node("match", _match)
    g.add_node("screen", _screen)
    g.add_node("qualify", _qualify)
    g.add_node("detect_check", _detect)
    g.add_node("verdict", verdict)

    g.set_entry_point("route")
    g.add_conditional_edges(
        "route", _route_edge,
        {"named": "named", "match": "match", "screen": "screen"},
    )
    g.add_edge("named", "qualify")
    g.add_edge("match", "qualify")
    g.add_edge("screen", "qualify")
    g.add_edge("qualify", "detect_check")   # never skipped, never conditional
    g.add_edge("detect_check", "verdict")
    g.add_edge("verdict", END)
    return g.compile()


async def qualify_question(question: str, bench: Bench) -> QualifierResult:
    graph = build(bench)
    out = await graph.ainvoke({"question": question, "notes": []})
    result: QualifierResult = out["result"]
    result.tool_calls = list(getattr(bench, "calls", []))
    return result
