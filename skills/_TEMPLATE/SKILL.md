---
name: amo-<short-name>
description: <One or two sentences. State the situation in the words a practitioner would use, not the card's formal trigger. This text is what the agent matches against to decide whether to load the skill, so it must contain the vocabulary a human would actually type. Max 1024 chars.>
situation_id: SIT-AMO-nnn
classification: judgment | solver
detectability: DIRECT | DERIVED | ABSENT
allowed-tools: match_situations, explain_qualifier, get_strategies, get_stack_model
---

# <Skill title>

## Trigger

<When to load this skill, in human language. Include the phrasings a planner would use,
not only the formal trigger condition. Cross-reference the card's trigger but do not
duplicate it — the card is the truth.>

**Do not load this skill when:** <the adjacent situation that looks similar and is not
this one. This line prevents the most common misfire.>

## Divergence note

<Why competent practitioners diverge here, stated as the axis of disagreement. One
paragraph. This is the section that stops the agent collapsing to a single answer.>

**The axis:** <name it — e.g. "which commitment class is being protected".>

## Solver boundary

<What is already solved, by which system, and correctly. State it as a concession.
Then state the residue that is not solved and is what this card covers.>

## Delegation posture

| Range across strategies | Meaning for presentation |
|---|---|
| ... | ... |

## Vocabulary

| A practitioner says | It means | Query as |
|---|---|---|
| ... | ... | ... |

> Customer overrides go in `vocabulary.<customer>.md` alongside this file and are merged
> at load time, most-specific-wins.

## Data model guidance

| Step | `system_class` | Entity | Join key |
|---|---|---|---|
| ... | ... | ... | ... |

**Availability check:** <which of these systems must exist in the instantiated stack
graph for this situation to be detectable at all, and what to say if one is absent.>

## Tool sequencing

1. ...

**Never** <the sequencing error this ordering prevents>.

## Strategies

<Names only, with the axis each one sits on. Preconditions, trade-offs and ceilings come
from `get_strategies` at runtime and are NOT duplicated here.>

## Response template

## Worked examples

### Example 1 — <the ordinary case>
### Example 2 — <the case where the low-effort strategy was correct>
### Example 3 — <the case that is not this situation>

## Failure modes

| Failure | Why it happens | Guard |
|---|---|---|
| ... | ... | ... |
