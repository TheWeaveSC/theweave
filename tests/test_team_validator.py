"""Validator (team doctor) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.doctor import FAIL, PASS
from weave.team.loader import TEMPLATES_DIR
from weave.team.validator import validate_team


def test_validate_team_templates_zero_failures() -> None:
    report = validate_team()
    assert report.failures() == 0
    statuses = {c.name: c.status for g in report.groups for c in g.checks}
    assert statuses["manifest"] == PASS
    assert statuses["seat-tiers"] == PASS
    assert statuses["tier-models"] == PASS
    assert statuses["hard-floors"] == PASS
    assert statuses["loop-phases"] == PASS
    assert statuses["hydrate"] == PASS


def _copy_templates_to(tmp_path: Path) -> Path:
    dest = tmp_path / "team"
    dest.mkdir()
    for f in TEMPLATES_DIR.glob("*.md"):
        (dest / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_validate_team_corrupted_seat_unknown_tier_fails(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    seat_path = dest / "entity-seat-Lucky.md"
    text = seat_path.read_text(encoding="utf-8")
    seat_path.write_text(
        text.replace("default_tier: standard", "default_tier: unknown-tier"),
        encoding="utf-8",
    )

    report = validate_team(dest)
    assert report.failures() >= 1
    fail_checks = [c for g in report.groups for c in g.checks if c.status == FAIL]
    assert any("entity-seat-Lucky.md" in (c.message + (c.detail or "")) for c in fail_checks)


def test_validate_team_missing_hub_fails(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    (dest / "entity-Team-Hub.md").unlink()

    report = validate_team(dest)
    assert report.failures() >= 1


def test_validate_team_exit_code_convention_matches_failures() -> None:
    report = validate_team()
    # Same convention as weave-cli doctor: exit code == number of failures.
    assert report.failures() == 0
