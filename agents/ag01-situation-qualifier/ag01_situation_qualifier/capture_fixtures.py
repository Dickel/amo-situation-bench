"""Refresh fixtures/amo.json from the live bench.

    python -m ag01_situation_qualifier.capture_fixtures

Run this after any bench reload. A stale fixture is worse than no fixture: the
offline tests keep passing while the live server has moved.
"""
from __future__ import annotations

import asyncio, json
from pathlib import Path

from .bench import LiveBench

SEED_ENTITIES = ["WO-4471", "WO-4482", "WO-4503", "PART-XR200", "WC-ASM02"]


async def main() -> None:
    b = LiveBench()
    listing = await b.call("list_situation_types")
    out = {
        "_note": "Real payloads captured from the live AMO bench with include_cypher=false.",
        "_captured": __import__("datetime").date.today().isoformat(),
        "list_situation_types": listing,
        "get_stack_model": await b.call("get_stack_model"),
        "explain_qualifier": {
            s["id"]: await b.call("explain_qualifier", situation_id=s["id"])
            for s in listing["situation_types"]
        },
        "match_situations": {},
    }
    for e in SEED_ENTITIES:
        res = await b.call("match_situations", entity_id=e)
        if res.get("found"):
            out["match_situations"][e] = res
    p = Path(__file__).parent / "fixtures" / "amo.json"
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {p}: {listing['count']} cards, "
          f"{len(out['match_situations'])} matched entities")


if __name__ == "__main__":
    asyncio.run(main())
