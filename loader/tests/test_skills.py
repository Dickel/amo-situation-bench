"""Skill-directory parser tests — pure Python, no database."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from loader.skills import SkillParseError, parse_skills_dir

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


@pytest.fixture(scope="module")
def skills():
    return parse_skills_dir(SKILLS_DIR)


def test_parses_every_skill_and_skips_the_template(skills):
    names = {s.name for s in skills}
    assert names == {
        "amo-situation-triage",
        "amo-part-contention",
        "amo-bottleneck-contention",
        "amo-yield-shortfall",
    }


def test_domain_inferred_from_name_prefix(skills):
    assert all(s.domain == "AMO" for s in skills)


def test_triage_skill_is_meta_and_has_no_situation_id(skills):
    triage = next(s for s in skills if s.name == "amo-situation-triage")
    assert triage.classification == "meta"
    assert triage.situation_id is None
    assert triage.is_triage


def test_situation_skills_carry_a_matching_situation_id(skills):
    m = {s.name: s.situation_id for s in skills if not s.is_triage}
    assert m == {
        "amo-part-contention": "SIT-AMO-001",
        "amo-bottleneck-contention": "SIT-AMO-004",
        "amo-yield-shortfall": "SIT-AMO-005",
    }


def test_body_and_allowed_tools_captured(skills):
    part = next(s for s in skills if s.name == "amo-part-contention")
    assert "match_situations" in part.allowed_tools
    assert part.body.startswith("#")
    assert "duration.between" not in part.body  # sanity: not a leak of a pattern


def test_missing_dir_returns_empty(tmp_path):
    assert parse_skills_dir(tmp_path / "nope") == []


def _write_skill(tmp_path: Path, name: str, frontmatter: str, body: str = "# X\n\ncontent") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\n{textwrap.dedent(frontmatter).strip()}\n---\n\n{body}\n")
    return tmp_path


def test_name_must_match_directory(tmp_path):
    root = _write_skill(tmp_path, "amo-foo", "name: amo-bar\nclassification: judgment\nsituation_id: SIT-AMO-009")
    with pytest.raises(SkillParseError, match="!= directory"):
        parse_skills_dir(root)


def test_meta_skill_must_not_name_a_situation(tmp_path):
    root = _write_skill(tmp_path, "amo-x", "name: amo-x\nclassification: meta\nsituation_id: SIT-AMO-001")
    with pytest.raises(SkillParseError, match="meta skill must not"):
        parse_skills_dir(root)


def test_non_meta_skill_must_name_a_situation(tmp_path):
    root = _write_skill(tmp_path, "amo-x", "name: amo-x\nclassification: judgment")
    with pytest.raises(SkillParseError, match="must name a situation_id"):
        parse_skills_dir(root)
