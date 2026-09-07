"""Typed output for AG-01.

The verdict is a Pydantic model rather than prose because three of the agent's
documented failure modes are only checkable against a structured field:

  - claiming ABSENT without checking the instantiated stack
      -> detectability_confirmed_against
  - fabricating a situation id
      -> situation_id is validated against list_situation_types
  - improvising a strategy set for something not in the bench
      -> verdict is a closed enum; there is no field to put strategies in
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    """The four outcomes of triage. Only the first leads anywhere else."""

    JUDGMENT_IN_BENCH = "JUDGMENT_IN_BENCH"
    SOLVER = "SOLVER"
    UNDETECTABLE_HERE = "UNDETECTABLE_HERE"
    NOT_IN_BENCH = "NOT_IN_BENCH"


class ConfirmedAgainst(str, Enum):
    INSTANTIATED_STACK = "instantiated_stack"
    REFERENCE_MODEL = "reference_model"
    NOT_CHECKED = "not_checked"


class SituationMatch(BaseModel):
    situation_id: str
    name: str
    classification: Literal["judgment", "solver"]
    detectability: Literal["DIRECT", "DERIVED", "ABSENT"]
    trigger_condition: str
    solver_boundary: str | None = None
    rationale: str | None = None
    matched_instances: list[str] = Field(default_factory=list)
    required_systems: list[str] = Field(default_factory=list)
    missing_systems: list[str] = Field(default_factory=list)
    handoff_skill: str | None = None


class QualifierResult(BaseModel):
    verdict: Verdict
    reasoning: str = Field(description="Why this verdict, in two or three sentences.")

    matches: list[SituationMatch] = Field(default_factory=list)

    detectability_confirmed_against: ConfirmedAgainst = ConfirmedAgainst.NOT_CHECKED
    solver_owner: str | None = Field(
        default=None,
        description="For SOLVER: the system or engine that already answers this.",
    )
    boundary_explanation: str | None = Field(
        default=None,
        description="For NOT_IN_BENCH: why it falls outside, so the answer is useful "
        "rather than only a refusal.",
    )

    tool_calls: list[str] = Field(
        default_factory=list, description="Ordered record of tools actually called."
    )

    @model_validator(mode="after")
    def _check_shape(self) -> "QualifierResult":
        if self.verdict is Verdict.JUDGMENT_IN_BENCH:
            if not self.matches:
                raise ValueError("JUDGMENT_IN_BENCH requires at least one match")
            for m in self.matches:
                if m.classification != "judgment":
                    raise ValueError(
                        f"{m.situation_id} is classified {m.classification}; "
                        "it cannot support a JUDGMENT_IN_BENCH verdict"
                    )
                if (
                    m.detectability == "ABSENT"
                    and self.detectability_confirmed_against
                    is not ConfirmedAgainst.INSTANTIATED_STACK
                ):
                    raise ValueError(
                        f"{m.situation_id} is ABSENT but detectability was confirmed "
                        f"against {self.detectability_confirmed_against.value}. "
                        "ABSENT may only be asserted against the instantiated stack."
                    )
        if self.verdict is Verdict.SOLVER and not self.solver_owner:
            raise ValueError("SOLVER requires solver_owner: name what answers it")
        if self.verdict is Verdict.NOT_IN_BENCH:
            if self.matches:
                raise ValueError("NOT_IN_BENCH cannot carry matches")
            if not self.boundary_explanation:
                raise ValueError(
                    "NOT_IN_BENCH requires boundary_explanation: explain the boundary, "
                    "do not only refuse"
                )
        if self.verdict is Verdict.UNDETECTABLE_HERE:
            if not self.matches or not all(m.missing_systems for m in self.matches):
                raise ValueError(
                    "UNDETECTABLE_HERE requires every match to carry missing_systems. "
                    "A mixed result reports JUDGMENT_IN_BENCH and keeps the "
                    "undetectable cards in matches, so the detectable half is not hidden."
                )
        return self


# Situation id -> skill directory. AG-01 hands off; it does not load these itself.
# SIT-AMO-002 and SIT-AMO-003 have no skill yet — AG-01 still qualifies them,
# it just has nothing to hand off to.
HANDOFF_SKILLS = {
    "SIT-AMO-001": "amo-part-contention",
    "SIT-AMO-004": "amo-bottleneck-contention",
    "SIT-AMO-005": "amo-yield-shortfall",
}
