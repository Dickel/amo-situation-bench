"""Derive what is live at a plant, by diffing its instantiation against the
reference model.

The point of the instantiation set: **blind spots are derived, not authored.**
Given which systems a plant runs, which interfaces are wired, and which bespoke
comparisons exist, the live blind-spot set and the reachable card set fall out
of a graph diff. Nobody writes them down per customer, so nobody can get them
wrong per customer.

Each plant card carries an `expected` block, which makes this a test oracle
rather than a report: if the derivation disagrees with the block, one of them is
wrong and the disagreement is the finding.

    python -m instances.derive                    # all plants, offline
    python -m instances.derive --plant PLANT-B
    python -m instances.derive --check            # exit 1 on any mismatch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent

# Card -> the system classes its detection depends on. Sourced from
# explain_qualifier: trigger_source_system_class plus the systems named in
# detectability_note for ABSENT cards.
CARD_SYSTEMS = {
    "SIT-AMO-001": {"ERP"},
    "SIT-AMO-002": {"ERP"},
    "SIT-AMO-003": {"PLM_ECM", "ERP"},
    "SIT-AMO-004": {"APS", "HUMAN_ROUTINE"},
    "SIT-AMO-005": {"MES", "ERP"},
}

# Card -> the blind spot it covers, keyed as sorted system pair.
CARD_BLIND_SPOT = {
    "SIT-AMO-003": "PLM_ECM-ERP",
    "SIT-AMO-004": "APS-HUMAN_ROUTINE",
    "SIT-AMO-005": "MES-ERP",
}

REFERENCE_BLIND_SPOTS = {
    "MES-ERP": "MES knows delivered quantity, ERP knows planned quantity, and no "
    "message carries the delta against the customer commitment",
    "APS-HUMAN_ROUTINE": "the solver reports infeasibility; nothing arbitrates "
    "between commitments when no feasible option satisfies all of them",
    "PLM_ECM-ERP": "no system compares ECO effectivity against already-released orders",
}

BASE_DETECTABILITY = {
    "SIT-AMO-001": "DERIVED",
    "SIT-AMO-002": "DERIVED",
    "SIT-AMO-003": "ABSENT",
    "SIT-AMO-004": "ABSENT",
    "SIT-AMO-005": "ABSENT",
}


def load_plants() -> dict[str, dict]:
    out = {}
    for p in sorted(HERE.glob("STACK-AMO-*.yaml")):
        d = yaml.safe_load(p.read_text())
        out[d["id"].replace("STACK-AMO-", "")] = d
    return out


def derive(plant: dict) -> dict:
    present = {s["system_class"] for s in plant["systems_present"]}
    closed = {
        b["closes_blind_spot"]: b for b in plant.get("bespoke_comparisons") or []
    }

    # A blind spot is live when both its systems are present AND no bespoke
    # comparison closes it. A blind spot whose systems are not both present is
    # not "closed" -- it is unreachable, which is a different and stronger fact.
    live, unreachable = [], []
    for key in REFERENCE_BLIND_SPOTS:
        systems = set(key.split("-", 1)) if key != "APS-HUMAN_ROUTINE" else {
            "APS", "HUMAN_ROUTINE"
        }
        if key == "PLM_ECM-ERP":
            systems = {"PLM_ECM", "ERP"}
        elif key == "MES-ERP":
            systems = {"MES", "ERP"}
        if not systems <= present:
            unreachable.append((key, sorted(systems - present)))
        elif key in closed:
            pass  # closed by a bespoke comparison; not live
        else:
            live.append(key)

    cards = {}
    for cid, needed in CARD_SYSTEMS.items():
        missing = sorted(needed - present)
        if missing:
            cards[cid] = {
                "verdict": "UNDETECTABLE_HERE",
                "missing": missing,
                "why": next(
                    (
                        s.get("note", "").strip().split(".")[0]
                        for s in plant.get("systems_absent") or []
                        if s["system_class"] in missing
                    ),
                    "",
                ),
            }
            continue
        det = BASE_DETECTABILITY[cid]
        bs = CARD_BLIND_SPOT.get(cid)
        if bs and bs in closed:
            det = closed[bs]["resulting_detectability"]
            cards[cid] = {
                "verdict": "JUDGMENT_IN_BENCH",
                "detectability": det,
                "downgraded_from": BASE_DETECTABILITY[cid],
                "closed_by": closed[bs]["description"].strip().split(".")[0],
            }
        else:
            cards[cid] = {"verdict": "JUDGMENT_IN_BENCH", "detectability": det}
    return {
        "plant": plant["id"],
        "name": plant["name"],
        "systems_present": sorted(present),
        "live_blind_spots": sorted(live),
        "unreachable_blind_spots": unreachable,
        "cards": cards,
    }


def compare(derived: dict, expected: dict) -> list[str]:
    errs = []
    if sorted(expected["live_blind_spots"]) != derived["live_blind_spots"]:
        errs.append(
            f"live_blind_spots: expected {sorted(expected['live_blind_spots'])}, "
            f"derived {derived['live_blind_spots']}"
        )
    for cid, exp in expected["cards"].items():
        got = derived["cards"][cid]
        if got["verdict"] != exp["verdict"]:
            errs.append(f"{cid}: expected {exp['verdict']}, derived {got['verdict']}")
        for k in ("detectability", "missing"):
            if k in exp and exp[k] != got.get(k):
                errs.append(f"{cid}.{k}: expected {exp[k]}, derived {got.get(k)}")
    return errs


def render(d: dict) -> str:
    L = [f"{d['plant']} — {d['name']}", f"  systems  {', '.join(d['systems_present'])}"]
    L.append(f"  live blind spots  {', '.join(d['live_blind_spots']) or 'none'}")
    for key, miss in d["unreachable_blind_spots"]:
        L.append(f"  unreachable       {key} (needs {', '.join(miss)})")
    L.append("")
    for cid, c in d["cards"].items():
        if c["verdict"] == "UNDETECTABLE_HERE":
            L.append(f"  {cid}  UNDETECTABLE_HERE   missing {', '.join(c['missing'])}")
            if c.get("why"):
                L.append(f"            {c['why']}")
        else:
            line = f"  {cid}  JUDGMENT_IN_BENCH   {c['detectability']}"
            if c.get("downgraded_from"):
                line += f"  (downgraded from {c['downgraded_from']})"
            L.append(line)
            if c.get("closed_by"):
                L.append(f"            closed by: {c['closed_by']}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(prog="derive")
    ap.add_argument("--plant")
    ap.add_argument("--check", action="store_true", help="exit 1 on any mismatch")
    a = ap.parse_args()

    plants = load_plants()
    if a.plant:
        plants = {k: v for k, v in plants.items() if a.plant in k}
    failures = 0
    for key, plant in plants.items():
        d = derive(plant)
        print(render(d))
        errs = compare(d, plant["expected"])
        if errs:
            failures += len(errs)
            for e in errs:
                print(f"  MISMATCH  {e}")
        else:
            print("  oracle: matches expected")
        print()
    if a.check:
        print(f"{failures} mismatch(es)")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
