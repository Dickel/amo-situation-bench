# AMO — Agentic Manufacturing Orchestration

**A synthetic factory, the short-horizon decisions inside it where good planners
disagree, and the graph, server and agent that let an AI reason about them
without pretending there is one right answer.**

Nothing in here is real. No customer data, no real orders, no real plants. The
plant is invented, the work orders are invented, and the vendors named
(SAP S/4HANA, Siemens Opcenter) are named only to borrow interface vocabulary.
What is real is the structure: the seams between systems, the shape of the
decisions that fall into them, and the discipline that stops an agent
collapsing a judgment call into a confident single answer.

---

## Why AMO

Manufacturing already has systems for almost everything. ERP holds the
commitments. APS chooses a sequence. MES records what the floor actually did.
PLM owns the design and its changes. Each is excellent at its job and each has
one thing in common: **it is a system of record for one function, usually at one
site.**

An MES is deployed per plant. It is configured around that plant's lines, its
work centres, its routings, its people. That is not a defect — it is what makes
it useful. But it means the MES cannot answer the question a planner is actually
holding on a Tuesday morning:

> *This part is short. Two programmes need it. One of them is for a customer we
> are already late to. Do I protect the programme, protect total flow, protect
> cash, or protect the supplier relationship — and can I still make the date I
> promised?*

That question spans ERP (the commitment), MES (what was really delivered), PLM
(whether the revision in flight is still valid), the supplier portal (whether
the promise date moved), and a human routine with no system of record at all
(the clear-to-build review where it actually gets decided). No system owns the
comparison, because a comparison across systems is nobody's system of record.

**AMO is the layer that does own it: a system of *action* that runs across
sites and across systems, from planning through to execution.** Not another
system of record. Not a better solver. The thing that notices a situation
nothing else can see, states the defensible moves and their trade-offs, and
knows how far it is allowed to act on its own.

### What qualifies as a situation

Every card in the bench passes one test:

> *Given the same numbers, would two competent practitioners land on the same
> move, or on two different defensible ones?*

If they would converge, a solver already owns it and it is not in here.
Netting, BOM explosion, date propagation, re-sequencing against a stated
objective — all solved, all deliberately out of scope. If they would diverge,
and both could defend the answer, it is a card.

This is also the boundary of the scope. **S&OE** — Sales & Operations Execution
— is the short-horizon cycle where the plan meets what actually happened and
someone has to re-decide: this week, this shift, this order. The planning cycle
above it (S&OP) is not in scope. The daily and weekly re-deciding is.

### The three layers, and why only one of them is agentic

| Layer | What it does | Test |
|---|---|---|
| Deterministic arithmetic | Explode the BOM, net against supply, propagate a date change, find the first period that goes short | Two competent planners compute the same number. No model belongs near it. |
| What-if and optimisation | Stage a change and recompute; compare before and after on delivery, coverage and cash | Can the objective be written as one function? Then optimise it, do not reason about it. |
| **Choosing between defensible answers** | Decide which option *this* plant should take, when coverage, cash and delivery are in genuine tension | Do two good practitioners disagree, and can both defend it? Only then is there something to teach. |

Simulation tells you what each option costs. It does not tell you which one to
take. That remainder is the whole subject of this repo.

Longer form: [dickel.sooriah.com/vao/manufacturing](https://dickel.sooriah.com/vao/manufacturing).

---

## What has been built

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  1 · THE SYNTHETIC PLANT                                                      ║
║  MODEL-AMO-PLANT-IT — nine system classes, their interfaces, their seams      ║
╚═══════════════════════════════════════════════════════════════════════════════╝

 ISA-95
 level
        IBP / S&OP              PLM / ECM              SUPPLIER PORTAL
  L4    planned independent     eBOM · ECO ·           promise dates
        requirements            work instructions
             │                       │   ╎                     │
             │                       │   ╎ BLIND-PLM-ERP       │
             │                       │   ╎ no system compares  │
             │                       │   ╎ ECO effectivity to  │
             │                       │   ╎ released orders     │
             │                       │   ╎ → SIT-AMO-003       │
             └───────────┐           │   ╎                     │
                         ▼           ▼   ╎                     ▼
  L4                  ╔══════════════════╧═════════════════════════╗
                      ║              E R P                         ║
                      ║  mBOM · routing · work orders · POs ·      ║
                      ║  component reservations · commitments      ║
                      ╚═══╤══════════════════════════════════╤═════╝
                          │                                  ╎
                          ▼                                  ╎ BLIND-MES-ERP
  L4/3    ╔═══════════════════════╗   ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ ╎ ERP holds planned
          ║        A P S          ║ ╌╌ HUMAN ROUTINE         ╎ quantity, MES holds
          ║ sequenced operation   ║   clear-to-build,        ╎ delivered quantity,
          ║ queue per work centre ║   daily tiering,         ╎ no message carries
          ║                       ║   overtime — no          ╎ the delta against
          ║                       ║   system of record       ╎ the commitment
          ╚═══════════╤═══════════╝     ▲                    ╎ → SIT-AMO-005
                      │      BLIND-APS-HUM                   ╎
                      │      solver reports infeasible;      ╎
                      │      nothing arbitrates between      ╎
                      │      commitments → SIT-AMO-004       ╎
                      ▼                                      ╎
  L3         ╔═════════════════╗                             ╎
             ║      M E S      ║══▶ QMS   ◀╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╯
             ║ confirmations · ║    inspection, NCR
             ║ demonstrated    ║
             ║ capacity        ║
             ╚════════╤════════╝
                      ▲
  L2          SCADA / HISTORIAN — machine state

  ═══  system of record        ╌╌╌  a seam: no system owns the comparison
  ───  interface, one hop

  Instantiated three ways:  PLANT-A  full stack, 9 systems, 3 seams live
                            PLANT-B  no APS, bespoke PLM→ERP integration, 6 systems
                            PLANT-C  no PLM/ECM, 7 systems
                                     │
                                     ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  2 · THE SITUATIONS                          data/amo-situations.md · v0.5    ║
╚═══════════════════════════════════════════════════════════════════════════════╝

  SIT-AMO-001  scarce common part contention
  SIT-AMO-002  supplier delivery slip with cascading need-date impact
  SIT-AMO-003  engineering change against released work-in-progress
  SIT-AMO-004  bottleneck slot contention under a committed sequence
  SIT-AMO-005  yield shortfall against a committed date

  Each card carries:
    trigger.source          emitting system, emission mode, latency class
    solver boundary         what is already solved and out of scope
    detectability           DIRECT · DERIVED · ABSENT
    strategies              system_of_action, writes, reversibility
                            (REVERSIBLE · COMPENSATING_ONLY · IRREVERSIBLE),
                            delegation_ceiling
    NO_ACTION               hold and absorb, as an explicit execution_path
                                     │
                          loader/  ── one command, one transaction
                                     ▼
                          ┌────────────────────┐
                          │  MEMGRAPH          │  every system_class must
                          │                    │  resolve to a :System node
                          └─────────┬──────────┘  or the load fails
                                    │
╔═══════════════════════════════════▼═══════════════════════════════════════════╗
║  3 · THE MCP SERVER       read-only · https://mcp.agenticgraph.net/amo/mcp    ║
╚═══════════════════════════════════════════════════════════════════════════════╝

   nine tools, each returning the Cypher it ran

   ┌── discovery ──────────────┐ ┌── qualification ──────────┐ ┌── context ─────────┐
   │ list_situation_types      │ │ explain_qualifier         │ │ read_order_context │
   │ get_stack_model           │ │ match_situations          │ │ read_commitments   │
   │ get_situation_footprint   │ │ get_skill                 │ │                    │
   └───────────────────────────┘ └───────────────────────────┘ └────────────────────┘
   ┌── strategy enumeration ───────────────────────────────────┐
   │ get_strategies                                            │
   └───────────────────────────────────────────────────────────┘
                                    │
                 ┌──────────────────┴──────────────────┐
                 ▼                                     ▼
╔════════════════════════════════════╗  ╔═══════════════════════════════════════╗
║  4 · SKILLS        skills/         ║  ║  5 · AGENTS        agents/            ║
╚════════════════════════════════════╝  ╚═══════════════════════════════════════╝

  amo-situation-triage                     AG-01 · situation qualifier
  amo-part-contention                      LangGraph · Python
  amo-bottleneck-contention
  amo-yield-shortfall                      route ─┬─ match  ──┐
  _TEMPLATE                                       └─ screen ──┴─ qualify ─
                                                    detect_check ─ verdict
  Each carries:
    divergence note   the axis on which        Returns one of four verdicts:
                      practitioners diverge      · judgment call — the spread
    solver boundary   what not to re-derive        and who owns the call
    delegation        the ceiling range           · a solver already answers
      posture         across strategies             this — which one
    vocabulary        local terms → field         · real, but undetectable at
                      values, overridable           this plant — which system
    tool sequencing   qualify before                is missing
                      enumerating strategies      · outside the bench

                                             get_strategies is not bound to AG-01
```

---

## The throughline

Take an S&OE decision an AI would happily invent a confident answer to, and give
it the structure to say instead: *this is judgment, here is the range of
defensible moves, here is who owns the call.*

---

## Try it

```bash
# talk to the live bench, nothing to install
npx @modelcontextprotocol/inspector https://mcp.agenticgraph.net/amo/mcp

# run the qualifier against the live server (Python 3.12+)
cd agents/ag01-situation-qualifier
pip install -r requirements.txt
python -m ag01_situation_qualifier.run "what's happening with WO-4471?"

# or load your own copy of the graph
pip install -r loader/requirements.txt
python -m loader.load                 # needs a Memgraph on bolt://localhost:7687
```

## Status

`[PROPOSED]` throughout. Five cards, one plant model (instantiated three ways),
four skills, one agent. The data is synthetic and the plant instantiations are
authored judgments, not observations from a real site. Growing toward ~20 cards
before it's called done.

Design notes and the decisions worth not relitigating are in
[`DECISIONS.md`](DECISIONS.md).
