---
name: amo-part-contention
description: Load when two or more open work orders require the same part number and projected availability is less than the sum of their requirements. Triggers on phrasings like "we're short on the housing", "both orders need the same bracket", "who gets the parts", "there isn't enough to cover both". Covers the allocation decision between competing consumers of one shortfall — not the netting, which MRP already does. Do not load for a single work order short of a part, which is a coverage problem with one consumer and no arbitration.
situation_id: SIT-AMO-001
classification: judgment
detectability: DERIVED
allowed-tools: match_situations, explain_qualifier, get_strategies, get_stack_model
---

# Scarce common part contention

## Trigger

Two or more open work orders require the same part number, and projected availability —
on hand plus incoming — is less than the sum of their required quantities.

**Do not load this skill when:**

- One work order is short. That is a coverage problem with a single consumer; expedite or
  wait, and there is nothing to arbitrate.
- The shortfall is at a work centre rather than on a part. That is SIT-AMO-004.
- Availability covers both and the issue is timing within the horizon. MRP's phasing
  answers it.

## Divergence note

MRP's output shape is one net requirement per item per period. That shape **structurally
cannot express a contention** between WO-4471 and WO-4482 — not because the engine is
weak, but because the object it emits has no slot for two competing consumers. The
shortfall is visible; the contention is not.

Given the same shortfall, one planner allocates to the earliest need date, because it is
simple and defensible on paper. Another protects the highest-tier account, because the
penalty schedule justifies it. A third splits and expedites the remainder, because
avoiding a hard miss on either order is worth the coordination cost. A fourth substitutes
a qualified alternate on one order and the contention disappears.

**The axis:** whether allocation follows time, contractual value, or risk-spreading —
and whether the contention can be dissolved rather than resolved.

## Solver boundary

Netting one item's supply against total demand is solved. MRP does it correctly every
run and AMO does not attempt it.

What is not solved, and not attempted by any system in the stack, is **allocation between
two competing consumers of the same shortfall**. State the concession before the claim.

## Detectability — read this before claiming value

This card is `DERIVED`, not `ABSENT`. The distinction matters and is frequently
over-stated in the other direction.

Everything needed is in the ERP: the reservations, the projected availability, the need
dates, the customer tiers. Nothing carries it across a system seam. What is missing is
not data — it is that **no report puts two consumers of one shortfall on the same page**
and no one owns the resulting decision.

That is a weaker claim than `ABSENT` and it must be made in the weaker form. Telling an
ERP-competent buyer that their system "cannot see this" when it demonstrably holds every
field is the fastest way to lose the room. The correct claim is that the data is present
and the comparison is unowned.

## Delegation posture

| Strategy | Ceiling | Presentation consequence |
|---|---|---|
| S1 Earliest need date | `UNSUPERVISED` | May be proposed as executable |
| S2 Protect highest tier | `UNSUPERVISED` | May be proposed as executable |
| S3 Split the allocation | `RECOMMEND` | Involves a supplier expedite with premium freight approval |
| S4 Substitute a qualified alternate | `COMMIT_WITH_REVIEW` | Bounded by the qualified alternate catalogue; engineering owns the catalogue |

S4's write is `COMPENSATING_ONLY` — a component substitution on an order BOM is undone by
a further change, not by a reversal. Say so when proposing it, because "we can always
change it back" is what a planner will assume and it is not what the system does.

## Vocabulary

| A practitioner says | It means | Query as |
|---|---|---|
| "we're short on X" | projected availability below total requirement for part X | on hand + incoming vs sum of reservations |
| "the housing" / "the bracket" / any nickname | a part number — resolve against the local naming convention | `part_number` |
| "both orders need it" | the contention itself | two or more reservations on one part |
| "who gets it" | the allocation decision — this card | — |
| "when's it landing" | incoming supply date | expected receipt date |
| "on order" / "on the water" | incoming, not on hand | incoming quantity |
| "split it" | strategy S3 | partial reservation on both |
| "is there an alternate" | strategy S4 | qualified alternate catalogue |
| "expedite it" | a component of S3, not a standalone answer | supplier expedite request |
| "tier one" | contractual customer priority | customer tier on the commitment |

Part nicknames are the single highest-value customer-specific override in this skill.
Every plant has them, none are in a system, and an agent that cannot resolve "the big
housing" to a part number is useless in a tiering meeting. Put them in
`vocabulary.<customer>.md`.

## Data model guidance

| Step | `system_class` | Entity | Join key |
|---|---|---|---|
| 1. Establish the shortfall | `ERP` | part, on hand, incoming | `part_number` |
| 2. Enumerate the consumers | `ERP` | reservations against the part | `reservation.work_order_id` |
| 3. Walk to the orders | `ERP` | work orders, need dates | `work_order_id` |
| 4. Walk to the commitments | `ERP` | sales order schedule lines, customer, tier | `confirmed_delivery_date` |
| 5. For S3 only | `SUPPLIER_PORTAL` | expedite feasibility on the shortfall | supplier + part |
| 6. For S4 only | `ERP` / `PLM_ECM` | qualified alternate catalogue | `part_number` |
| 7. For S2 only | `MES` | dispatch priority, so the floor matches the allocation | `work_order_id` |

**Step 7 is the one that gets forgotten.** S2 has two action paths, not one: the ERP
reservation reallocation *and* an MES dispatch-priority update. An allocation decision
that does not reach the floor is a decision that gets silently reversed by whoever picks
first. Present both paths or the strategy is incomplete.

## Tool sequencing

1. `match_situations(part_number or work_order_id)` — confirm the card fires and get the
   competing orders.
2. `explain_qualifier("SIT-AMO-001")` — confirm judgment.
3. `get_stack_model()` — confirm `ERP` present; check `SUPPLIER_PORTAL` and `MES` before
   presenting S3 and S2 respectively.
4. `get_strategies("SIT-AMO-001")`.
5. Present, with both action paths shown for any multi-path strategy.

**Never compute the netting.** If asked how short, read it; do not derive it. MRP's
number is the number of record and a hand-derived one that disagrees will be assumed
wrong even when it is right.

## Strategies

| ID | Name | Allocation basis |
|---|---|---|
| S1 | Allocate to earliest need date | time |
| S2 | Protect the highest-tier account | contractual value |
| S3 | Split the allocation | spread the risk |
| S4 | Substitute a qualified alternate | dissolve the contention |

S4 is categorically different from the other three: it does not allocate the shortfall,
it removes it. Present it first when its precondition holds, because a planner working
through an allocation frame will not think to ask.

## Response template

```
SITUATION — SIT-AMO-001, scarce common part contention
Part <number> (<local name>): available <a>, required <b>, short <b−a>.

COMPETING CONSUMERS
  <WO-A> qty <q>, need <date>, <customer>, tier <t>, commit <date>
  <WO-B> qty <q>, need <date>, <customer>, tier <t>, commit <date>

OPTIONS
  S4 Substitute alternate      [COMMIT_WITH_REVIEW]  removes the contention if qualified
  S1 Earliest need date        [UNSUPERVISED]        ERP reservation
  S2 Protect highest tier      [UNSUPERVISED]        ERP reservation + MES dispatch priority
  S3 Split and expedite        [RECOMMEND]           ERP split + supplier expedite
  <one line of trade-off per option, from get_strategies>

WHAT WOULD NARROW THIS
  <alternate qualification status; penalty schedule; expedite lead time vs need-date gap>

NOTE
  Detection here is DERIVED, not absent: every field is in the ERP. What is missing is a
  view that puts both consumers of the shortfall on one page, and an owner for the
  decision that follows.
```

## Worked examples

### Example 1 — the ordinary case

Part is short by 40 across two orders needing 60 and 30. Need dates are eleven days apart.
One order carries a tier-1 commitment, the other tier-3. The agent checks the alternate
catalogue first (none qualified), then presents S1, S2 and S3 with both action paths shown
for S2. The planner takes S2, and the MES dispatch-priority path is what stops the floor
consuming against the original reservation the following morning.

### Example 2 — the contention dissolved

Same shortfall. A superseding part number is engineering-qualified for one of the two
builds. S4 removes the contention entirely and the other three options become moot. The
agent presents S4 first and flags that the BOM write is `COMPENSATING_ONLY` — reverting
means another change, not an undo. Presenting S4 fourth, after three allocation options,
would have led the planner to allocate before learning the contention was avoidable.

### Example 3 — this is not the situation

"WO-4471 is short 40 on the housing." One order. No competing consumer, therefore no
allocation decision. Expedite or wait; MRP and the buyer own it. The correct response
says so and stops.

## Failure modes

| Failure | Why it happens | Guard |
|---|---|---|
| Claiming `ABSENT` | `ABSENT` is the stronger sales claim | This card is `DERIVED`; the data is all in the ERP |
| Presenting S2 without the MES path | The ERP write looks complete | Two action paths; the floor must match the allocation |
| Presenting S4 last | Allocation options feel like the answer set | Present S4 first when qualified |
| Firing on a single-consumer shortage | Shortage pattern-matches | Two or more consumers required |
| Deriving the shortfall by hand | It is easy arithmetic | Read MRP's number; do not recompute it |
| Treating a BOM substitution as reversible | "We can change it back" | `COMPENSATING_ONLY` |
