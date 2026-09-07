# Decisions

Why the bench is shaped the way it is. Read this before proposing a structural
change — most of these were paid for once already.

## The taxonomy

**A card is a situation where competent practitioners diverge.** The test is
applied before anything is written: given identical data, would two good planners
converge on one move (→ a solver owns it, not a card) or diverge into different
defensible ones (→ a card, and the divergence is the content). `solver`-classified
cards are not loaded.

**`detectability` is the field that decides what to build.** `DIRECT` (a system
already alerts on it), `DERIVED` (computable from one system's data, nobody
computes it), `ABSENT` (visible only by comparing two systems, neither owns the
comparison). `ABSENT` is the strongest claim and is only assertable against a
specific plant, never the reference model.

**One card names systems for three different jobs, usually different systems.**
`trigger.source` = detection, `system_of_record` = evidence, and each strategy's
`system_of_action` = where that strategy's write lands. Collapsing them is why an
earlier version could describe a situation but not tell you what to build.

**`delegation_ceiling` is derived from the write paths, not authored.** A
strategy's ceiling is the minimum across its action paths: an APS resequence is
reversible, a works-council overtime authorisation is not, so the strategy caps
at `RECOMMEND`. It can't drift from the paths because it's computed from them.

## The graph

**Memgraph, one instance.** Every node carries a `domain` property (always
`"AMO"` here). One instance can hold more than one domain; isolation is enforced
inline in every `trigger.pattern` (`{domain: $domain}`, parser-checked), not by
which process runs.

**The reference model is a graph, and `system_class` is a reference into it.**
Not a free-text label — an unresolvable `system_class` is a load error. That
constraint is what stops the vocabulary drifting card by card.

**`system_of_action` loads as `ActionPath` nodes**, not a flattened list of maps.
Memgraph properties can't hold nested maps, and a flattened one is unqueryable
anyway.

**`SENDS` is reified as an `:Interface` node** (`System -[:SENDS]-> Interface
{cadence} -[:TO]-> System`, `Interface -[:CARRIES]-> DataObject`) so cadence and
the carried object are queryable.

**`WRITES` → `DataObject` is strict exact-name match only.** The `writes` values
are field-level (`planned_start_date`) and DataObject names are object-level;
they were authored independently, and fuzzy matching produced false edges. Most
`writes` stay as `ActionPath.writes` properties with no edge. Flagged, not
forced.

**The load is one transaction.** Wipe + rebuild commit atomically, so a
concurrent MCP read sees the whole old graph or the whole new one — never a
half-built state. `get_stack_model` also runs its sub-queries in one read
transaction, and returns an explicit `stack_model_incomplete` error rather than
a plausible-looking empty stack if it ever finds zero systems.

## Provenance & bitemporality

**Property pair on the node, not a `SUPERSEDES` revision chain.**
`source_valid_from`/`_to` (valid time — when the source believed it) and
`graph_ingested_at`/`_updated_at` (transaction time — when the bench learned it)
as plain properties. A change predicate that needs the prior value uses
`tracked_transitions`, not a chain. Query simplicity, load simplicity, and
revision chains have no operating precedent at scale.

**`tracked_transitions[].retains` is fixed at 1**, parser-enforced. A field
declared transition-tracked carries `<field>` / `<field>_prior` /
`<field>_changed_at`. Anything above one prior value is a revision chain wearing
a different name, and is rejected at load.

**`write_semantics` (`APPEND_ONLY` | `UPDATABLE`) is on the `:DataObject`, not
the `:System`.** ERP masters both updatable objects (work order dates) and
append-only ones (goods movements, confirmations); a single system-level value
forces a wrong answer for the most important system. `default_write_semantics`
on `:System` is the fallback.

**Four load assertions, all errors:** `source_system_class` resolves; no
`source_valid_to` on an APPEND_ONLY object; `extraction_run_id` present on any
node presenting as extracted; `retains == 1`.

## The MCP server

**Read-only. No `run_query(cypher)` is ever exposed.** Each tool wraps one fixed,
known-good Cypher pattern. `match_situations` is the one place stored query text
runs — the dataset's own vetted `trigger.pattern` strings, never caller input.

**`include_cypher` does exactly one thing:** decide whether the `cypher` key is
attached. The response is otherwise byte-identical. A parity guard
(`mcp_server/tests/`) asserts this across every tool and is wired into CI against
the deployed server.

**No auth on the public tier.** Rate limiting is a runaway-client guard, not a
security boundary — synthetic data only. It returns a `{"error": "rate_limited"}`
payload rather than raising (the SDK masks raised exception text).

## Skills

**A skill is the operating envelope; the card is the truth.** A skill carries
what the graph doesn't — human-language recognition, tool-call order, response
shape, local vocabulary. It restates strategy *names* for readability and
nothing else. If a skill's strategy list disagrees with `get_strategies`, the
card wins and the skill is stale.

**Skills load into the graph as `:Skill` nodes**, so `get_skill` is a Cypher
read like every other tool and the container image never ships the `skills/`
tree.

## Dataset discipline

**Mechanical fixes are applied and flagged; judgment content is never touched.**
A broken Cypher function or a YAML typo is fixed in place and documented in the
card's `pattern_note`. The strategies, trade-offs and qualifier tests are never
paraphrased.

**`duration.between()` does not exist on Memgraph** (Neo4j-only). Use direct date
subtraction: `(later - earlier).day` (Memgraph's `Duration` exposes `.day`,
singular).

**`date()` in a trigger tested against a fixed sample is fragile and stays
flagged, not fixed.** `SIT-AMO-005` compares a sample field to wall-clock today,
so whether it fires depends on the calendar day. The trigger logic is fine for a
live system; the fragility is testing it against a static fixture. Candidate fix
(an `as_of` field) is a call for whoever owns the card content.
