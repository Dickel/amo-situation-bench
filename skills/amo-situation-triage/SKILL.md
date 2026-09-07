---
name: amo-situation-triage
description: Load for every AMO turn before any situation-specific skill. Establishes whether the thing the user is describing is a situation type in the bench at all, whether it is judgment or solver territory, and whether the systems needed to detect it exist at this customer. Use when a planner describes a problem in plain language ("we're short on the housing", "ASM02 is jammed", "the line only made 18 of 22"), when asked what is happening today, or before enumerating any strategies. Also use to decline gracefully when the situation is not in the bench.
classification: meta
allowed-tools: match_situations, list_situation_types, explain_qualifier, get_stack_model
---

# AMO Situation Triage

## Outcome

Every AMO answer starts here. This skill turns an unstructured description into one of
four verdicts, and only the first of them leads anywhere else:

1. **Judgment situation in the bench** → load the situation skill, present the defensible set.
2. **Solver situation** → name the system that already answers it. Do not enumerate strategies.
3. **In the bench but undetectable here** → the situation is real; the systems needed to see it are not present at this customer. Say so.
4. **Not in the bench** → say so plainly. Do not improvise a strategy set.

Verdict 4 is not a failure. A bench that answers everything is a bench with no boundary,
and the boundary is the product.

---

## The qualification test

The single criterion, applied before anything else:

> Given identical data, would two competent practitioners converge on the same action?
>
> **Converge → solver territory.** Some system already computes this, or should. AMO does
> not add value and should not pretend to.
>
> **Diverge, both with defensible reasoning → judgment territory.** This belongs in the
> bench, and the divergence is the thing being captured.

Signals that a description is **solver** territory:

- The user asks "what is the answer" and there is one.
- The disagreement, if any, is about data quality, not about what to do.
- A named engine (MRP, APS, RCCP, CRP) already produces the output.
- The only reason it feels hard is that nobody has looked.

Signals that a description is **judgment** territory:

- Two or more parties would be harmed and the question is which.
- The right answer depends on something not in any system (account value, relationship
  history, works council appetite, how much the last expedite cost politically).
- A defensible answer exists that involves doing nothing.

---

## Detectability, and why it changes the answer

Every card carries a `detectability` value. It is not a technical footnote — it changes
what the agent is allowed to claim.

| Value | Meaning | What the agent may say |
|---|---|---|
| `DIRECT` | One system emits this condition as a signal | "The system flagged this" |
| `DERIVED` | Computable from one system's data, but not emitted | "This is computable from ERP data; nothing surfaces it today" |
| `ABSENT` | Visible only by comparing two systems, and **neither owns the comparison** | "No system in your stack can see this. It is visible only by comparing X and Y, and no interface carries that comparison" |

`ABSENT` is the strongest claim AMO makes and the one most often over-stated. Before
asserting it, confirm against the **instantiated** stack graph for this customer, not the
reference model. A customer with a bespoke integration that already carries the
comparison has a `DERIVED` situation, not an `ABSENT` one, and telling them otherwise
destroys credibility in one sentence.

---

## Tool sequencing

```
1. match_situations(entity_id)          → which cards fire on this instance
2. explain_qualifier(situation_id)      → confirm judgment vs solver, and why
3. get_stack_model()                    → confirm the systems needed are present
4. [load the situation skill]
5. get_strategies(situation_id)         → the defensible set, with ceilings
```

**Never call `get_strategies` before `explain_qualifier`.** Presenting a set of options
for a solver-territory problem is the single most damaging failure this bench can produce:
it makes arbitration look like indecision, and it is the error a sceptical scheduler is
watching for.

**Never call `get_strategies` for a card that `match_situations` did not return.** If the
user insists a situation is happening and the graph disagrees, report the disagreement.
The data may be stale, the entity ID may be wrong, or the situation may be real and
undetectable — all three are useful answers and all three are different.

---

## Vocabulary — cross-cutting

| A practitioner says | It usually means | Disambiguate by asking |
|---|---|---|
| "we're short" | a coverage gap on a component | which part, and short against what — a work order or a commitment |
| "we're going to miss" | projected completion is past a customer commitment date | which order, and is the commitment contractual or internal |
| "the line is down" | equipment stoppage — **not an AMO situation**, this is maintenance | — |
| "we can't build it" | clear-to-build failure; could be material, could be an engineering hold | is anything missing, or is something blocked |
| "it's jammed" / "backed up" | queue at a work centre exceeding capacity in the horizon | which work centre |
| "the change dropped" | an engineering change was released | effectivity date, and are orders already released |
| "we made short" | confirmed yield below planned quantity | which operation — final or intermediate |
| "expedite it" | a proposed strategy, not a situation | what is the underlying situation |

Note the last row. Users frequently describe the *strategy they have already chosen*
rather than the situation. Recover the situation first. A user who says "expedite the
housing" has skipped the arbitration, and the arbitration is the point.

---

## Presentation rules

**For a judgment situation, every answer contains:**

1. The situation, named, with its card ID.
2. What is at stake and for whom — the parties whose interests conflict.
3. The **full defensible set**, each with its trade-off, its `delegation_ceiling`, and
   where the write lands.
4. The low-effort option, always, where the card carries one.
5. What is missing that would narrow the set — the information that would let a human
   decide faster.

**Never:**

- Rank the strategies as if one is correct, unless the preconditions of the others
  demonstrably fail. Then say *which precondition failed*, which is a fact, rather than
  which option is best, which is a judgment the user owns.
- Propose an action above its `delegation_ceiling`. Name the authority instead.
- Present a strategy whose preconditions are unverified without marking them unverified.

---

## Failure modes

| Failure | Why it happens | Guard |
|---|---|---|
| Options presented for a solver problem | Skipping `explain_qualifier` | Step 2 is mandatory |
| Single recommendation for a judgment card | The model's default helpfulness | Divergence note in every situation skill |
| `ABSENT` claimed against the reference model | Convenient, and the reference model is what loads by default | Check the instantiated stack graph |
| Strategy set invented for an unbenched situation | Reluctance to say no | Verdict 4 is a valid outcome |
| The low-effort option omitted | It reads as unhelpful | It is a strategy; list it |
| Accepting the user's proposed action as the situation | The user led with it | Recover the situation before enumerating |
