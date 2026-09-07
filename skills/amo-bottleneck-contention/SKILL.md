---
name: amo-bottleneck-contention
description: Load when a constrained work centre cannot satisfy every queued commitment in the horizon and the affected work orders belong to different customers. Triggers on phrasings like "ASM02 is over capacity", "the solver says it's infeasible", "we can't fit both orders through the bottleneck", "who do we bump", "the sequence doesn't work any more". Covers the arbitration that begins after a finite-capacity scheduler has reported infeasibility — not the sequencing itself, which is solved. Do not load for a single-customer queue overload, which is a sequencing problem, not an arbitration.
situation_id: SIT-AMO-004
classification: judgment
detectability: ABSENT
allowed-tools: match_situations, explain_qualifier, get_strategies, get_stack_model
---

# Bottleneck slot contention under a committed sequence

## Trigger

A committed sequence at a constrained work centre has become infeasible — remaining
available capacity in the horizon is less than the sum of queued operations' remaining
run time — **and two or more affected work orders carry commitments to different
customers**.

Both halves matter. Capacity shortfall alone is a sequencing problem. Capacity shortfall
plus competing external commitments is an arbitration, and only the second is this card.

**Do not load this skill when:**

- All affected orders belong to one customer. That is sequencing; the APS answers it.
- The constraint is material rather than capacity. That is SIT-AMO-001.
- The work centre is down rather than full. That is maintenance, not AMO.

## Divergence note

Two schedulers looking at the same infeasible queue will not choose the same order.

One protects the highest-tier account, because the penalty schedule and the relationship
justify it. One sequences for aggregate on-time delivery, because that is what the plant
is measured on and it is defensible to anyone reading the scorecard. A third holds the
committed sequence entirely, because the changeover pattern it was optimised for is worth
more than the marginal commitment, and the staging downstream is already sunk.

All three are defensible. None is derivable from the data in the systems, because the
deciding input — what the missed relationship is worth relative to a measured OTD
point — exists in no system.

**The axis:** which commitment class is being protected — contractual tier, aggregate
measured performance, or schedule stability.

## Solver boundary

Finite-capacity sequencing is solved, and mature APS engines solve it well: resource
calendars, the changeover matrix, operation precedence, feasibility checking. AMO does
not attempt any of it and should say so plainly when asked.

This card covers only what begins when the solver's feasible set contains no option
satisfying every commitment. **The solver produces the option space; the judgment is
which option to take.** Stating the concession first is not a weakness in the argument,
it is the argument.

## Delegation posture

| Strategy class | Ceiling | Presentation consequence |
|---|---|---|
| Resequencing within the APS | `UNSUPERVISED` | May be proposed as an executable action |
| Holding the sequence | `RECOMMEND` | Present as a choice, not an action |
| Adding capacity | `RECOMMEND` | Never propose directly — labour authorisation sits with operations management and works council constraints apply |
| Customer re-commitment | `RECOMMEND` | Never propose directly — name the programme or customer support owner |

The two strategies that actually resolve the contention rather than allocating the pain
are both capped at `RECOMMEND` and both write outside any system. That asymmetry is worth
stating to the user: the cheapest real fixes are the ones no system can execute.

## Vocabulary

| A practitioner says | It means | Query as |
|---|---|---|
| "the bottleneck" / "the constraint" | the work centre with the binding capacity limit in this horizon | `WorkCentre` where `is_constrained = true` |
| "ASM02", "the CNC cell", "the paint line" | a specific work centre — resolve to the ID | `work_centre_id` |
| "it's infeasible" | the APS returned no feasible sequence satisfying all due dates | APS solver status |
| "bump" / "push out" / "displace" | move an operation later in the sequence | resequencing |
| "pull in" / "jump the queue" | move an operation earlier | resequencing |
| "the horizon" | the scheduling window the APS committed | `available_minutes_in_horizon` |
| "tier one" / "the big account" | contractual customer priority | customer tier on the commitment |
| "run time left" | remaining operation duration, not total | remaining run time |
| "we'll just work Saturday" | overtime authorisation — strategy S4, not a fact | `HUMAN_TASK`, operations management |

## Data model guidance

| Step | `system_class` | Entity | Join key |
|---|---|---|---|
| 1. Identify the constraint | `APS` | work centre, available minutes in horizon | `work_centre_id` |
| 2. Enumerate the queue | `APS` | sequenced operations, remaining run time | `aps_sequence_id` |
| 3. Walk to the orders | `ERP` | production orders | `production_order` |
| 4. Walk to the commitments | `ERP` | sales order schedule lines, confirmed dates | `confirmed_delivery_date` |
| 5. Establish the parties | `ERP` | customer, tier | commitment → customer |

**Availability check.** This card is `ABSENT` because the arbitration inputs sit on both
sides of a seam: the APS holds the infeasibility, the ERP holds the commitments and the
customer tiers, and no interface carries the comparison. Confirm both `APS` and `ERP`
resolve to nodes in the **instantiated** stack graph before asserting that. A customer
with no APS has a different situation entirely — the infeasibility is never even
detected, which is a stronger finding and should be reported as such.

## Tool sequencing

1. `match_situations(work_centre_id or production_order)` — confirm the card fires.
2. `explain_qualifier("SIT-AMO-004")` — confirm judgment, and retrieve the reasoning.
3. `get_stack_model()` — confirm `APS` and `ERP` both present.
4. `get_strategies("SIT-AMO-004")` — the defensible set with live ceilings.
5. Present.

**Never compute a sequence.** If the user asks what the new order should be, the answer
is that the APS produces it once the priority basis is forced, and the priority basis is
the decision in front of them. Offering a hand-computed sequence crosses the solver
boundary and is wrong more often than the engine.

## Strategies

Names only. Preconditions, trade-offs and ceilings come from `get_strategies` at runtime
and are deliberately not duplicated here.

| ID | Name | Axis it sits on |
|---|---|---|
| S1 | Hold the committed sequence | schedule stability — the low-effort option |
| S2 | Resequence to protect the highest-tier commitment | contractual tier |
| S3 | Resequence to protect total flow | aggregate measured performance |
| S4 | Add capacity rather than choose | expand the feasible set |
| S5 | Re-commit with the customer | move the constraint |

S1 must always be presented. It is the option a scheduler will reach for and it is
defensible; omitting it makes the situation look more urgent than it is and makes the
agent look like it is selling intervention.

S4 and S5 are the only two that resolve the contention without allocating harm. Both are
`RECOMMEND` and both execute outside any system. Say that.

## Response template

```
SITUATION — SIT-AMO-004, bottleneck slot contention
Work centre <ID>: <shortfall> minutes short across <n> queued operations in the horizon.

AT STAKE
  <Customer A> — <order>, commit <date>, tier <t>
  <Customer B> — <order>, commit <date>, tier <t>
  No feasible sequence satisfies both.

OPTIONS
  S1 Hold the sequence         [RECOMMEND]     no write
  S2 Protect highest tier      [UNSUPERVISED]  APS sequence + ERP dates
  S3 Protect total flow        [UNSUPERVISED]  APS sequence
  S4 Add capacity              [RECOMMEND]     operations mgmt — outside systems
  S5 Re-commit with customer   [RECOMMEND]     programme — outside systems
  <one line of trade-off per option, from get_strategies>

WHAT WOULD NARROW THIS
  <the missing input — penalty schedule, tier currency, overtime availability>

NOTE
  Detection here is ABSENT: the infeasibility is in the APS, the commitments are in the
  ERP, and no interface compares them.
```

## Worked examples

### Example 1 — the ordinary case

WC-ASM02 is 340 minutes short across six queued operations. Two orders carry commitments:
one to a tier-1 aerospace account with a stated penalty schedule, one to a tier-3
distributor with no penalty clause. The agent presents all five options, notes that S2's
precondition (tier defined and current) is satisfied and S4's (labour within agreement
limits) is unverified, and does not choose. The scheduler chooses S2 in ninety seconds
because the presentation made the tier basis explicit rather than implied.

### Example 2 — the low-effort option was correct

Same shortfall, but both commitments are internal transfer orders to a sister plant with
two weeks of slack downstream, and the current sequence was optimised around a long paint
changeover. S1 is correct: resequencing would cost a changeover to protect commitments
that are not at risk. An agent that omitted S1 would have manufactured an intervention.
This is the case that justifies the rule.

### Example 3 — this is not the situation

"ASM02 is backed up, we're two days behind." Single customer across the whole queue.
No competing commitments, therefore no arbitration. This is sequencing, the APS answers
it, and the correct response is to say so and stop. Loading this skill and presenting
five options here would be the characteristic failure of the whole approach.

## Failure modes

| Failure | Why it happens | Guard |
|---|---|---|
| Computing a proposed sequence | It feels like the helpful answer | Solver boundary; the APS produces it once the basis is set |
| Omitting S1 | Doing nothing reads as unhelpful | S1 is always presented |
| Proposing overtime directly | It is the obvious fix | `RECOMMEND` only; works council constraints apply |
| Firing on a single-customer queue | Capacity shortfall pattern-matches | Both halves of the trigger are required |
| Claiming `ABSENT` without checking | The reference model loads by default | Check the instantiated stack graph |
| Ranking S2 above S3 | Tier sounds more important than flow | Both are `UNSUPERVISED` and both are defensible; the user owns the axis |
