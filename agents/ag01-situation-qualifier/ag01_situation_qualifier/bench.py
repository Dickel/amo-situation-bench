"""Access to the AMO situation bench.

Two transports behind one interface.

  LiveBench     talks to the MCP server over streamable HTTP.
  FixtureBench  replays captured payloads from fixtures/amo.json.

The fixture transport exists so the graph, the verdict schema and the eval suite
can be exercised without network access or model spend. Every fixture is a real
response captured from the live server, not an invented shape.

AG-01 deliberately has access to four tools. `get_strategies` is not among them.
The triage skill's rule -- never enumerate strategies before qualifying -- is
therefore enforced by the tool surface rather than by an instruction, which is
the stronger form. If AG-01 could call it, a sufficiently confident model
eventually would.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

AMO_MCP_URL = "https://mcp.sooriah.com/amo/mcp"

ALLOWED_TOOLS = (
    "list_situation_types",
    "match_situations",
    "explain_qualifier",
    "get_stack_model",
)


class Bench(Protocol):
    async def call(self, tool: str, **kwargs: Any) -> dict: ...


class _Recorder:
    """Mixin: keeps the ordered tool-call log the verdict carries."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, tool: str, kwargs: dict) -> None:
        if tool not in ALLOWED_TOOLS:
            raise PermissionError(
                f"AG-01 may not call {tool!r}. Allowed: {', '.join(ALLOWED_TOOLS)}. "
                "Strategy enumeration belongs to AG-04, after qualification."
            )
        arg = kwargs.get("situation_id") or kwargs.get("entity_id") or ""
        self.calls.append(f"{tool}({arg})" if arg else f"{tool}()")


class FixtureBench(_Recorder):
    """Offline replay. Unknown keys raise rather than returning empty.

    `plant` overlays a stack instantiation from instances/ onto the reference
    model, so the same fixtures exercise all four verdicts. Without it the stack
    is the reference model and no ABSENT claim is assertable -- which is correct
    behaviour, and useless as a test.
    """

    def __init__(
        self, path: str | Path | None = None, plant: str | None = None
    ) -> None:
        super().__init__()
        path = Path(path or Path(__file__).parent / "fixtures" / "amo.json")
        self._data = json.loads(path.read_text())
        self._plant = load_plant(plant) if plant else None

    async def call(self, tool: str, **kwargs: Any) -> dict:
        self._record(tool, kwargs)
        if tool == "list_situation_types":
            return self._data["list_situation_types"]
        if tool == "get_stack_model":
            stack = dict(self._data["get_stack_model"])
            if self._plant:
                stack = apply_plant(stack, self._plant)
            return stack
        if tool == "explain_qualifier":
            sid = kwargs["situation_id"]
            try:
                return self._data["explain_qualifier"][sid]
            except KeyError:
                raise KeyError(f"no explain_qualifier fixture for {sid}") from None
        if tool == "match_situations":
            eid = kwargs["entity_id"]
            hit = self._data["match_situations"].get(eid)
            # A miss is a real answer from this tool, not a fixture gap.
            return hit or {"entity_id": eid, "found": False, "matches": []}
        raise ValueError(f"unhandled tool {tool}")


class LiveBench(_Recorder):
    """Streamable-HTTP MCP client against the deployed bench."""

    def __init__(self, url: str = AMO_MCP_URL) -> None:
        super().__init__()
        self.url = url

    async def call(self, tool: str, **kwargs: Any) -> dict:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        self._record(tool, kwargs)
        kwargs.setdefault("include_cypher", False)
        async with streamable_http_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, kwargs)
        return json.loads(result.content[0].text)


async def known_situation_ids(bench: Bench) -> set[str]:
    """The id allowlist. A verdict citing anything outside this set is a
    fabrication, and is rejected before it reaches the caller."""
    listing = await bench.call("list_situation_types")
    return {s["id"] for s in listing["situation_types"]}


def systems_in_stack(stack: dict) -> set[str]:
    """System classes present in the *instantiated* stack.

    On the reference model this returns the reference set. Against a customer
    instantiation it returns what that customer actually runs, which is the
    only basis on which ABSENT may be asserted.
    """
    out: set[str] = set()
    for s in stack.get("systems") or []:
        cls = s.get("system_class") if isinstance(s, dict) else None
        if cls:
            out.add(cls)
    return out


def is_instantiated(stack: dict) -> bool:
    """True when the stack model describes a specific customer rather than the
    reference landscape.

    The reference model carries no `instance_of`. Until a customer stack exists,
    this returns False everywhere -- which is correct, and which is what stops
    AG-01 asserting ABSENT on the strength of the reference model alone.
    """
    return bool(stack.get("instance_of") or stack.get("customer"))


# --------------------------------------------------------------------------- #
# Stack instantiation
# --------------------------------------------------------------------------- #

def _find_instances_dir() -> Path:
    """Locate instances/ by walking up from this file.

    Works whether the package sits in a repo (repo/agents/<pkg>/) or in the
    standalone distribution (ag01/<pkg>/), so the same code runs in both without
    a path constant that is wrong in one of them.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "instances"
        if candidate.is_dir() and any(candidate.glob("STACK-AMO-*.yaml")):
            return candidate
    return here.parents[1] / "instances"


INSTANCES_DIR = _find_instances_dir()

_SPOT_KEYS = {
    frozenset({"PLM_ECM", "ERP"}): "PLM_ECM-ERP",
    frozenset({"MES", "ERP"}): "MES-ERP",
    frozenset({"APS", "HUMAN_ROUTINE"}): "APS-HUMAN_ROUTINE",
}


def load_plant(name: str) -> dict:
    """Load a stack instantiation by id or short name (`PLANT-B`, `B`)."""
    import yaml

    short = name.upper().removeprefix("STACK-AMO-").removeprefix("PLANT-")
    for candidate in (name, f"STACK-AMO-PLANT-{short}"):
        p = INSTANCES_DIR / f"{candidate}.yaml"
        if p.exists():
            return yaml.safe_load(p.read_text())
    available = sorted(p.stem for p in INSTANCES_DIR.glob("STACK-AMO-*.yaml"))
    raise FileNotFoundError(f"no stack instance {name!r}. Available: {available}")


def apply_plant(reference: dict, plant: dict) -> dict:
    """Project the reference model through a plant instantiation.

    Systems the plant does not run are removed. Blind spots closed by a bespoke
    comparison are moved to `closed_blind_spots` with the reason, so a card whose
    ABSENT claim rested on one can be downgraded rather than over-claimed.

    A blind spot whose systems are not both present is dropped entirely: it is
    not closed, it is unreachable, and the card that covers it is
    UNDETECTABLE_HERE rather than weakened.
    """
    present = {s["system_class"] for s in plant["systems_present"]}
    closed = {b["closes_blind_spot"]: b for b in plant.get("bespoke_comparisons") or []}

    out = dict(reference)
    out["id"] = plant["id"]
    out["name"] = plant["name"]
    out["instance_of"] = plant["instance_of"]
    out["customer"] = plant["customer"]
    out["systems"] = [
        s for s in reference.get("systems") or [] if s.get("system_class") in present
    ]
    out["interfaces"] = [
        i
        for i in reference.get("interfaces") or []
        if i.get("from") in present and i.get("to") in present
    ]
    live, shut = [], []
    for bs in reference.get("known_blind_spots") or []:
        systems = set(bs.get("systems") or [])
        if not systems <= present:
            continue
        key = _SPOT_KEYS.get(frozenset(systems), "-".join(sorted(systems)))
        if key in closed:
            shut.append(
                {
                    **bs,
                    "closed_by": closed[key]["description"],
                    "resulting_detectability": closed[key]["resulting_detectability"],
                }
            )
        else:
            live.append(bs)
    out["known_blind_spots"] = live
    out["closed_blind_spots"] = shut
    return out
