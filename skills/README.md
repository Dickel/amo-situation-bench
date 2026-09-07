# AMO Agent Skills — v0.1

Skills are structured documents loaded **on demand** that give an AMO agent the
operational knowledge surrounding one situation type. They are not the situation card.

| Artifact | Owns | Lives in |
|---|---|---|
| Situation card (`SIT-AMO-nnn`) | trigger, classification, detectability, strategies, delegation ceilings, solver boundary | the graph, served by MCP |
| **Skill** | how to recognise the situation from human language, which order to call tools, what a complete answer looks like, what the local vocabulary means | this repo |
| Agent (`*.agent.yaml`) | which routine it serves, which skills it may load, which situations are in scope, its delegation defaults | this repo |

**The card is the truth. The skill is the operating envelope.** If a strategy list appears
in a skill and disagrees with `get_strategies`, the card wins and the skill is stale.
Skills restate strategy names for readability only, never preconditions or ceilings.

---

## Why skills are separate from agent instructions

Agent instructions define universal behaviour: tone, safety boundaries, the standing rule
that judgment situations are never collapsed to a single recommendation. Those load every
turn.

Skills carry domain knowledge and load only when the trigger matches. A daily-tiering
agent that loaded all thirteen situation domains on every turn would spend most of its
context on situations that are not happening, and would reliably miss the one that is.

---

## Required sections

Every AMO skill carries these. The first three are the ones that make it an AMO skill
rather than a generic retrieval skill.

| Section | Purpose |
|---|---|
| **Divergence note** | *Why* competent practitioners diverge here, and on what axis. The machine-readable form of the qualification test. Prevents the agent collapsing to a single answer. |
| **Solver boundary** | What is already solved and out of scope. Prevents the agent re-deriving the schedule or the netting. |
| **Delegation posture** | The ceiling range across strategies and what a ceiling means for presentation. Prevents the agent proposing an action above its authority. |
| Trigger | Recognition from human language, not only from a graph match. |
| Vocabulary | Local terms → field values. Customer-overridable. The highest-accuracy-per-line section. |
| Data model guidance | Which `system_class` nodes, in what order, joined on what. |
| Tool sequencing | The fixed order. Qualify before enumerating strategies. |
| Response template | What a complete answer contains. |
| Examples | Two or three worked instances, including at least one where the low-effort strategy was correct. |
| Failure modes | The specific wrong answers this skill exists to prevent. |

---

## Hard rules for every skill

1. **Never present a single strategy for a `judgment` card.** Present the defensible set
   with its trade-offs. If the agent has a view, it is stated as a lean with the reason,
   never as the answer.
2. **Always include the low-effort option.** Where the card carries a `NO_ACTION`
   execution path, it is a strategy and must be listed. Omitting it makes every situation
   look like it demands intervention.
3. **Never cross the solver boundary.** Do not compute the sequence, the netting, or the
   feasibility. Call the kernel service or state that the solver already answered it.
4. **Never propose an action above the strategy's `delegation_ceiling`.** State who holds
   the authority instead.
5. **Never state a fact about a system the stack model says is absent at this customer.**
   Check the instantiated stack graph, not the reference model.

---

## Repo layout

```
skills/
  README.md
  _TEMPLATE/SKILL.md
  amo-situation-triage/          # cross-cutting; loaded by every AMO agent
    SKILL.md
    evals/evals.json
  amo-part-contention/           # SIT-AMO-001
  amo-bottleneck-contention/     # SIT-AMO-004
  amo-yield-shortfall/           # SIT-AMO-005
```

One skill per situation type, plus one triage skill loaded by every agent. A skill that
covers two situation types has two triggers and will load for the wrong one — split it.

## Exposure

Skills are versioned here in Git. The loader also copies each into the graph as a
`:Skill` node, so the MCP server can serve it with `get_skill(situation_id)` — a
fixed Cypher read like every other tool — without shipping the `skills/` tree in
the container image. Versioning them here rather than in the graph makes a
customer's vocabulary override a pull request with a diff, not an untracked UI
edit.

## Provenance of the strategy content

The three situation skills restate strategy names, delegation ceilings, action paths and
solver boundaries drawn from the situation cards as served by the MCP server, not
invented. Cross-checked against `get_strategies` / `explain_qualifier`:

| Skill | Card | `get_strategies` / `explain_qualifier` agreement |
|---|---|---|
| `amo-part-contention` | SIT-AMO-001 | S1–S4 names, ceilings, S2 dual action path, S4 `COMPENSATING_ONLY`, `DERIVED`, solver boundary — exact |
| `amo-bottleneck-contention` | SIT-AMO-004 | S1–S5 names, S1 `NO_ACTION`/`RECOMMEND`, S2–S3 `UNSUPERVISED`, S4–S5 `RECOMMEND`, `ABSENT`, solver boundary — exact |
| `amo-yield-shortfall` | SIT-AMO-005 | S1–S4 names, ceilings, no `NO_ACTION` path, `ABSENT` (MES vs ERP), solver boundary — exact |

If a future card edit moves a ceiling or renames a strategy, the skill's Delegation
posture / Strategies / Response template sections go stale and must be re-synced from
`get_strategies`. The card wins.

## Status

`[PROPOSED]` — none of these skills has been run against a live agent. The eval suites
define the intended behaviour, not observed behaviour. Cards SIT-AMO-002 and SIT-AMO-003
have no skill yet.
