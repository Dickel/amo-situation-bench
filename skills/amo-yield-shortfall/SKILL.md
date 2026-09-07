---
name: amo-yield-shortfall
description: Load when a final operation confirms fewer good units than planned and the replenishment lead time for the shortfall exceeds the slack remaining against a customer commitment. Triggers on phrasings like "we only made 18 of 22", "we scrapped three at final test", "the order closed short", "we're going to be short on the shipment". Covers the arbitration between shipping short, expediting a rerun, robbing another order, and re-committing. Do not load for a shortfall discovered at an intermediate operation with recovery time still in the routing, or where slack against the commitment absorbs the rerun.
situation_id: SIT-AMO-005
classification: judgment
detectability: ABSENT
allowed-tools: match_situations, explain_qualifier, get_strategies, get_stack_model
---

# Confirmed yield falls short of planned quantity against a committed date

## Trigger

The final operation on a work order confirms a yield below the planned quantity, **and**
the replenishment lead time for the shortfall exceeds the slack remaining against the
customer commitment.

The second condition is what makes it a situation. A short confirmation with three weeks
of slack is a data point; the same shortfall with two days of slack is an arbitration.

**Do not load this skill when:**

- The shortfall is at an intermediate operation and the routing still has recovery time.
- Slack against the commitment exceeds the replenishment lead time. MRP handles it.
- The shortfall is a rework hold rather than scrap. The units exist; this is a different
  and generally easier problem.

## Divergence note

The moment a final operation confirms short against a tight commitment, four people give
four answers.

Customer support ships what exists and backfills, because most contracts tolerate a
partial and the commit date is what the scorecard measures. Production control expedites
a replacement through the routing, because a complete on-time shipment is what was
promised. A scheduler robs a lower-priority order already built, because it is free and
instant. The programme manager calls the customer, because a two-day push costs nothing
in cash and everything else costs something.

Each is right under different conditions, and the conditions that separate them —
whether the contract tolerates a partial, what the account's tolerance for a date push
actually is, whether the order being robbed has an owner who will notice — are largely
undocumented.

**The axis:** where the shortfall is absorbed — by the customer's receiving dock, by the
plant's cost base, by another order, or by the relationship.

## Solver boundary

Re-netting the shortfall and generating a replacement planned order is solved. The next
MRP run does it automatically and correctly, and AMO should not reimplement it.

What is not solved is that the replacement order carries a full lead time against a
commitment that has already passed, and **no system compares those two facts**. The
arithmetic is not the problem. The silence is.

That sentence is the cleanest statement of the AMO value claim in the whole bench. Use it.

## Delegation posture

| Strategy class | Ceiling | Presentation consequence |
|---|---|---|
| Reallocate from another order in flight | `UNSUPERVISED` | May be proposed as executable |
| Ship short / expedite a rerun | `COMMIT_WITH_REVIEW` | Propose with an explicit review step named |
| Re-commit the full quantity | `RECOMMEND` | Never propose directly — programme or customer support owns it |

Note the ranking is inverted relative to intuition. The strategy with the **highest**
autonomy is the one that quietly moves the problem onto another order whose owner did not
agree to it. Flag that explicitly when presenting S3: high delegation ceiling is not the
same as low consequence, and this is the case that proves it.

## Vocabulary

| A practitioner says | It means | Query as |
|---|---|---|
| "made short" / "came up short" | confirmed yield below planned quantity | confirmed qty vs planned qty on the final operation |
| "scrapped" | units failed and are unrecoverable | scrap quantity on the confirmation |
| "on hold" / "in rework" | units exist but are not good yet — **not this card** | — |
| "final test" / "last op" | the final operation in the routing | final operation flag |
| "the slack" | days between projected completion and the commit date | commit date minus projected completion |
| "ship what we've got" | strategy S1 | partial shipment |
| "run a replacement" / "cut a new order" | strategy S2 | replacement production order |
| "rob" / "borrow from" / "steal off" | strategy S3 — reallocate from another order | stock reallocation between commitments |
| "the customer will take it late" | an assumption behind S4, usually unverified | mark unverified |

The "rob / borrow / steal" row matters. The vernacular is casual and the action is
`UNSUPERVISED` in the card, so a user saying "just rob it off the other order" will get
executed if the agent takes the phrasing at face value. Surface the displaced order's
commitment before acting.

## Data model guidance

| Step | `system_class` | Entity | Join key |
|---|---|---|---|
| 1. Detect the shortfall | `MES` | confirmation on the final operation | confirmation → operation |
| 2. Get the planned quantity | `ERP` | production order | `production_order` |
| 3. Get the commitment | `ERP` | sales order schedule line | `confirmed_delivery_date` |
| 4. Compute slack | derived | commit date − projected completion | — |
| 5. Get replenishment lead time | `ERP` | routing + material lead time | — |
| 6. For S3 only: find candidates | `ERP` | other orders, same configuration, more slack | `stock_allocation` |

**Confirmations are append-only.** Corrections arrive as reversal documents, never as
edits. Never read "the latest confirmation" as the current quantity — sum the unreversed
confirmations. An agent that reads the latest record will report the wrong shortfall
whenever a correction has been posted, which is exactly when the situation is most
sensitive.

**Availability check.** `MES` and `ERP` must both resolve in the instantiated stack graph.
The `ABSENT` claim here is specifically: MES knows delivered quantity, ERP knows planned
quantity, and no message carries the delta against the customer commitment. If the
customer has built a bespoke reconciliation, this is `DERIVED`, not `ABSENT`, and the
value claim must be restated accordingly.

## Tool sequencing

1. `match_situations(production_order)` — confirm the card fires.
2. `explain_qualifier("SIT-AMO-005")` — confirm judgment.
3. `get_stack_model()` — confirm `MES` and `ERP` present.
4. `get_strategies("SIT-AMO-005")` — the defensible set.
5. If S3 is in play, resolve the candidate donor order **and its commitment** before
   presenting. S3 without naming who absorbs it is not a presentation of a strategy, it
   is a concealment of one.
6. Present.

## Strategies

| ID | Name | Where the shortfall is absorbed |
|---|---|---|
| S1 | Ship short, backfill later | the customer's receiving dock |
| S2 | Expedite a rerun of the shortfall | the plant's cost base |
| S3 | Reallocate from another order in flight | another order's owner |
| S4 | Re-commit the full quantity with the customer | the relationship |

Every option in this card costs someone something. There is no free option and no
`NO_ACTION` path — unlike SIT-AMO-004, doing nothing here is not defensible, because the
commitment fails silently. Say that when presenting: the absence of a hold-and-absorb
option is itself information.

## Response template

```
SITUATION — SIT-AMO-005, confirmed yield shortfall
Order <ID>: confirmed <n> of <m> at final operation. Shortfall <d> units.
Commitment <date>, slack <x> days. Replenishment lead time <y> days. Gap <y−x> days.

AT STAKE
  <Customer>, <order>, <quantity>, commit <date>

OPTIONS — every option costs someone; there is no hold-and-absorb path here
  S1 Ship short, backfill      [COMMIT_WITH_REVIEW]  ERP delivery split
  S2 Expedite a rerun          [COMMIT_WITH_REVIEW]  ERP order + APS priority
  S3 Reallocate from <order>   [UNSUPERVISED]        absorbs onto <that customer>
  S4 Re-commit full quantity   [RECOMMEND]           programme owns this
  <one line of trade-off per option, from get_strategies>

WHAT WOULD NARROW THIS
  <partial-shipment tolerance on the contract; donor order's real slack;
   whether the shortfall is a matched-pair item>

NOTE
  Detection here is ABSENT: MES holds the delivered quantity, ERP holds the planned
  quantity, and no message carries the delta against the commitment.
```

## Worked examples

### Example 1 — the ordinary case

Order confirms 18 of 22 at final test. Commit is in four days; replenishment lead time is
eleven. The agent presents all four, notes that S1's precondition (contract tolerates
partial) is unverified and flags it, and identifies a donor order for S3 with nine days
of slack — naming the customer who would absorb it. Customer support takes S1 in two
minutes because the contract question was surfaced as the deciding input rather than
buried in a trade-off sentence.

### Example 2 — the high-ceiling option was the dangerous one

Same shortfall. A scheduler says "just rob it off the Pratt order." S3 is
`UNSUPERVISED` and the agent could execute. The donor order turns out to be a matched-pair
assembly whose commitment is tighter than the requesting order's once the sister unit is
accounted for. The agent surfaces the donor's commitment before acting and the reallocation
is abandoned. The card's ceiling was correct and insufficient on its own — sequencing step 5
is what caught it.

### Example 3 — this is not the situation

Order confirms 18 of 22 at final test, commit is in five weeks. Slack exceeds lead time.
MRP nets the shortfall, a replacement order appears in the next run, and nobody needs to
decide anything. Not a situation. The correct response names the fact that slack absorbs
it and stops.

## Failure modes

| Failure | Why it happens | Guard |
|---|---|---|
| Reading the latest confirmation as current quantity | Confirmations look like records | Sum unreversed; corrections are reversal documents |
| Executing S3 on a casual verbal request | High ceiling plus casual vernacular | Resolve and name the donor commitment first |
| Firing where slack absorbs the rerun | The shortfall is visible; the slack is not | Both trigger conditions required |
| Firing on a rework hold | "Short" is used for both | Rework units exist; scrap units do not |
| Presenting a hold-and-absorb option | Habit from other cards | This card has none; say so |
| Assuming partial shipment is acceptable | It usually is | Mark unverified unless the contract term is retrieved |
