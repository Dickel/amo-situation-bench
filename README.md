# AMO — Agentic Manufacturing Orchestration

**A small public dataset of the S&OE decisions where good planners disagree — plus
the graph, the server, and the first agent that let an AI reason about them
without pretending there's one right answer.**

S&OE — Sales & Operations Execution — is the short-horizon cycle where the plan
meets what actually happened on the floor and someone has to re-decide: this
week, this shift, this order. It's where a supplier slips, a batch comes up
short, an engineering change lands mid-build. The planning cycle above it (S&OP)
is not in scope here; the daily and weekly re-deciding is.

Every situation in the bench passes one test: *given the same numbers, would two
competent practitioners land on the same move, or two different defensible ones?*
If they'd converge, a solver already owns it and it's not in here. If they'd
diverge, it's a card.

Nothing is real. No customer data, no real orders, no real plants. Public vendors
(SAP S/4HANA, Siemens Opcenter) are named only to borrow interface vocabulary.

---

## 🛠️ What's in here

**cards** · [`data/amo-situations.md`](data/amo-situations.md) · Markdown + YAML
Five S&OE situations where the hard part isn't the arithmetic — it's the call. A
shared part two orders both need. A supplier date that slips past the buffer. An
engineering change that lands mid-build. A bottleneck that can't fit everyone. A
batch that comes up short. Each card says what fires it, what a solver already
handles, and the three-to-five strategies nobody agrees on — each with how
reversible it is and how far you'd trust an agent to run it alone.

**the plant model** · [`data/amo-situations.md`](data/amo-situations.md) · a graph
A map of the systems a factory runs — ERP, MES, APS, PLM, the shop floor — what
each one knows, and the seams between them where a problem is visible from
neither side. Every "nobody can see this today" claim in the cards hangs off one
of those seams.

**loader** · [`loader/`](loader/) · Python
Turns the cards into a Memgraph graph you can query. One command, one transaction
— a reader never catches it half-built. It also checks every card's trigger
against its own example and tells you which ones don't fire.

**MCP server** · [`mcp_server/`](mcp_server/) · Python · [live](https://mcp.sooriah.com/amo/mcp)
A read-only API an AI agent connects to. Ask it what situation a work order is
in, what the competing strategies are, or which systems would have to be wired
together to even notice the problem. It hands back the exact query it ran, every
time.

**skills** · [`skills/`](skills/)
Short playbooks, one per situation, that teach an agent to recognise it from
plain language and what a complete answer looks like — always the full set of
options with their trade-offs, never a single recommendation.

**AG-01, the qualifier** · [`agents/ag01-situation-qualifier/`](agents/ag01-situation-qualifier/) · Python + LangGraph
The first agent. Ask it "what's going on with WO-4471?" and it tells you one of
four things: this is a judgment call (here's the spread), a solver already
answers this (here's which one), it's real but invisible at your plant (here's
the missing system), or it's outside the bench entirely. It will not list
strategies — that's the next agent's job, and it's blocked from calling that
tool at all.

---

## The throughline

Take an S&OE decision an AI would happily invent a confident answer to, and give
it the structure to say instead: *this is judgment, here's the range of
defensible moves, here's who owns the call.*

---

## Try it

```bash
# talk to the live bench, nothing to install
npx @modelcontextprotocol/inspector https://mcp.sooriah.com/amo/mcp

# run the qualifier against the live server (Python 3.12+)
cd agents/ag01-situation-qualifier
pip install -r requirements.txt
python -m ag01_situation_qualifier.run "what's happening with WO-4471?"

# or load your own copy of the graph
pip install -r loader/requirements.txt
python -m loader.load                 # needs a Memgraph on bolt://localhost:7687
```

## Status

`[PROPOSED]` throughout. Five cards, one plant model, four skills, one agent. The
data is synthetic and the plant instantiations are authored judgments, not
observations from a real site. Growing toward ~20 cards before it's called done.

Design notes and the decisions worth not relitigating are in
[`DECISIONS.md`](DECISIONS.md).
