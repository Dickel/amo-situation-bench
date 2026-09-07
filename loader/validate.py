"""Validate every situation card's trigger.pattern against its own sample_instance.

For each card, in isolation (graph wiped, only that card's entities + edges +
sample values loaded), run the raw `trigger.pattern` — with `domain` bound as a
parameter, since patterns reference `{domain: $domain}` inline on every node —
and record one of:

  OK        the pattern parsed and returned >= 1 row  -> the trigger fires on
            the instance the card says should satisfy it
  NO_MATCH  the pattern parsed but returned 0 rows    -> the pattern and the
            sample_instance disagree; the trigger is underspecified or wrong
  ERROR     the pattern did not parse / used something Memgraph does not
            support

Findings are reported, not silently patched.

    python -m loader.validate [--file ...] [--no-reload]

By default the graph is left seeded with a full load afterwards; --no-reload
leaves it empty.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from .cards import Card, parse_file
from . import db
from .load import DEFAULT_FILE, DEFAULT_SKILLS_DIR, run as full_load
from .skills import parse_skills_dir


@dataclass
class Result:
    card: Card
    status: str  # OK | NO_MATCH | ERROR
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def validate_card(session, card: Card) -> Result:
    for cypher, params in [db.wipe(), *db.card_only_statements(card)]:
        session.run(cypher, **params)
    try:
        rows = list(session.run(card.trigger_pattern, domain=card.domain))
    except Exception as exc:  # noqa: BLE001 - we want any Cypher failure verbatim
        return Result(card, "ERROR", _one_line(exc))
    if rows:
        return Result(card, "OK", f"{len(rows)} row(s)")
    return Result(card, "NO_MATCH", "pattern returned 0 rows against its sample_instance")


def validate_all(cards: list[Card]) -> list[Result]:
    results: list[Result] = []
    with db.driver() as drv:
        with drv.session() as session:
            for card in cards:
                results.append(validate_card(session, card))
    return results


def _one_line(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


def _print_table(results: list[Result]) -> None:
    width = max((len(r.card.id) for r in results), default=8)
    print(f"\n{'card'.ljust(width)}  status    detail")
    print(f"{'-' * width}  --------  ------")
    for r in results:
        print(f"{r.card.id.ljust(width)}  {r.status.ljust(8)}  {r.detail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--no-reload", action="store_true", help="leave the graph empty afterwards")
    args = ap.parse_args(argv)

    ds = parse_file(args.file)
    cards = [c for c in ds.situations if c.is_judgment]
    results = validate_all(cards)
    _print_table(results)

    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} patterns fire on their own sample_instance.")
    for r in failed:
        print(f"\n  {r.card.id} — {r.status}")
        print(f"    {r.detail}")
        print("    pattern:")
        for line in r.card.trigger_pattern.splitlines():
            print(f"      {line}")

    if not args.no_reload:
        loaded_ids = {c.id for c in cards}
        skills = [
            s for s in parse_skills_dir(DEFAULT_SKILLS_DIR)
            if s.is_triage or s.situation_id in loaded_ids
        ]
        counts, _ = full_load(cards, ds.reference_models, keep=False, skills=skills)
        print(
            f"\nGraph reloaded: {counts['nodes']} nodes, {counts['relationships']} relationships."
        )
    else:
        print("\nGraph left empty (--no-reload).")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
