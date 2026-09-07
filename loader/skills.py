"""Parse the `skills/` directory into structured skill documents.

Pure Python — no database. `parse_skills_dir()` is the entry point.

A skill (`skills/<name>/SKILL.md`) is the on-demand operating envelope around
one situation type — human-language recognition, tool-call order, response
shape, local vocabulary (see `skills/README.md`). The situation card stays the
source of truth; the skill only restates strategy *names* for readability.

Skills are versioned in Git, not authored in the graph — but the loader copies
each one into the graph as a `:Skill` node so the MCP server can serve it with
`get_skill(situation_id)` (a fixed Cypher read, like every other tool) instead
of shipping the `skills/` tree in the container image.

Frontmatter is a small YAML block between `---` fences:

    name: amo-part-contention
    situation_id: SIT-AMO-001          # absent on the cross-cutting triage skill
    classification: judgment | solver | meta
    detectability: DIRECT | DERIVED | ABSENT     # optional
    allowed-tools: a, b, c

Domain is inferred from the `name` prefix (`amo-` -> AMO).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NAME_RE = re.compile(r"^amo-[a-z0-9-]+$")
SITUATION_ID_RE = re.compile(r"^SIT-AMO-\d{3,}$")


class SkillParseError(ValueError):
    """A SKILL.md is present but malformed."""


@dataclass(frozen=True)
class SkillDoc:
    name: str
    domain: str
    classification: str            # judgment | solver | meta
    body: str                      # everything after the frontmatter
    description: str = ""
    situation_id: str | None = None   # None for the cross-cutting triage skill
    detectability: str | None = None
    allowed_tools: list[str] = field(default_factory=list)

    @property
    def is_triage(self) -> bool:
        return self.situation_id is None


def parse_skills_dir(path: str | Path) -> list[SkillDoc]:
    root = Path(path)
    if not root.is_dir():
        return []
    out: list[SkillDoc] = []
    seen: set[str] = set()
    for skill_md in sorted(root.glob("*/SKILL.md")):
        if skill_md.parent.name == "_TEMPLATE":
            continue
        doc = _parse_one(skill_md)
        if doc.name in seen:
            raise SkillParseError(f"duplicate skill name {doc.name!r}")
        seen.add(doc.name)
        out.append(doc)
    return out


def _parse_one(skill_md: Path) -> SkillDoc:
    text = skill_md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillParseError(f"{skill_md}: no YAML frontmatter block")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"{skill_md}: frontmatter did not parse: {exc}") from exc
    if not isinstance(fm, dict):
        raise SkillParseError(f"{skill_md}: frontmatter is not a mapping")

    name = str(fm.get("name", "")).strip()
    if not _NAME_RE.match(name):
        raise SkillParseError(f"{skill_md}: name {name!r} is not `amo-<slug>`")
    if name != skill_md.parent.name:
        raise SkillParseError(
            f"{skill_md}: frontmatter name {name!r} != directory {skill_md.parent.name!r}"
        )
    domain = name.split("-", 1)[0].upper()

    classification = str(fm.get("classification", "")).strip()
    if classification not in {"judgment", "solver", "meta"}:
        raise SkillParseError(
            f"{skill_md}: classification {classification!r} not judgment|solver|meta"
        )

    sid = fm.get("situation_id")
    situation_id = str(sid).strip() if sid else None
    if situation_id is not None and not SITUATION_ID_RE.match(situation_id):
        raise SkillParseError(f"{skill_md}: situation_id {situation_id!r} malformed")
    if classification == "meta" and situation_id is not None:
        raise SkillParseError(f"{skill_md}: a meta skill must not name a situation_id")
    if classification != "meta" and situation_id is None:
        raise SkillParseError(f"{skill_md}: a non-meta skill must name a situation_id")
    if situation_id and not situation_id.startswith(f"SIT-{domain}-"):
        raise SkillParseError(
            f"{skill_md}: situation_id {situation_id!r} is not in domain {domain}"
        )

    tools_raw: Any = fm.get("allowed-tools") or fm.get("allowed_tools") or []
    if isinstance(tools_raw, str):
        tools_raw = [t.strip() for t in tools_raw.split(",")]
    allowed_tools = [str(t).strip() for t in tools_raw if str(t).strip()]

    body = m.group(2).strip()
    if not body:
        raise SkillParseError(f"{skill_md}: no body after the frontmatter")

    return SkillDoc(
        name=name,
        domain=domain,
        classification=classification,
        body=body,
        description=str(fm.get("description", "")).strip(),
        situation_id=situation_id,
        detectability=(str(fm["detectability"]).strip() if fm.get("detectability") else None),
        allowed_tools=allowed_tools,
    )
