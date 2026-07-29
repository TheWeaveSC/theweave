"""Loader validation tests for the Org Team Engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.team.loader import TEMPLATES_DIR, load_manifest
from weave.team.models import (
    CANONICAL_HARD_FLOORS,
    CANONICAL_LOOP_PHASES,
    TeamManifestError,
    Tier,
)


def test_templates_dir_exists() -> None:
    assert TEMPLATES_DIR.is_dir()


def test_load_manifest_from_templates_has_9_seats() -> None:
    manifest = load_manifest()
    assert len(manifest.seats) == 9
    names = {s.name for s in manifest.seats}
    assert names == {
        "Director", "Sonnet", "Clutch", "Diamond", "Lucky",
        "Watchdog", "Coco", "Sterling", "Timmy",
    }


def test_load_manifest_has_6_loop_phases() -> None:
    manifest = load_manifest()
    assert len(manifest.loop_phases) == 6
    assert {p.name for p in manifest.loop_phases} == set(CANONICAL_LOOP_PHASES)


def test_load_manifest_has_5_hard_floors() -> None:
    manifest = load_manifest()
    assert set(manifest.hard_floors) == set(CANONICAL_HARD_FLOORS)


def test_load_manifest_has_3_tiers_in_routing_policy() -> None:
    manifest = load_manifest()
    assert set(manifest.routing_policy.tiers.keys()) == {"mechanical", "standard", "hard"}


def test_load_manifest_seats_sorted_deterministically() -> None:
    manifest = load_manifest()
    names = [s.name for s in manifest.seats]
    assert names == sorted(names)


def test_load_manifest_hub_version_is_1() -> None:
    manifest = load_manifest()
    assert manifest.hub_version == 1


def test_load_manifest_governance_champion_is_sonnet() -> None:
    manifest = load_manifest()
    assert manifest.governance_champion == "Sonnet"


# ---------- malformed template handling ----------

def _copy_templates_to(tmp_path: Path) -> Path:
    dest = tmp_path / "team"
    dest.mkdir()
    for f in TEMPLATES_DIR.glob("*.md"):
        (dest / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_missing_default_tier_raises_naming_file_and_field(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    seat_path = dest / "entity-seat-Lucky.md"
    text = seat_path.read_text(encoding="utf-8")
    # Strip the default_tier line entirely.
    new_text = "\n".join(
        line for line in text.splitlines() if not line.startswith("default_tier:")
    ) + "\n"
    seat_path.write_text(new_text, encoding="utf-8")

    with pytest.raises(TeamManifestError) as excinfo:
        load_manifest(dest)
    msg = str(excinfo.value)
    assert "entity-seat-Lucky.md" in msg
    assert "default_tier" in msg


def test_unknown_tier_value_raises(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    seat_path = dest / "entity-seat-Lucky.md"
    text = seat_path.read_text(encoding="utf-8")
    new_text = text.replace("default_tier: standard", "default_tier: nonsense-tier")
    seat_path.write_text(new_text, encoding="utf-8")

    with pytest.raises(TeamManifestError) as excinfo:
        load_manifest(dest)
    assert "entity-seat-Lucky.md" in str(excinfo.value)


def test_missing_hub_raises(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    (dest / "entity-Team-Hub.md").unlink()
    with pytest.raises(TeamManifestError, match="entity-Team-Hub"):
        load_manifest(dest)


def test_missing_sop_raises(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    (dest / "entity-OrgTeam-SOP.md").unlink()
    with pytest.raises(TeamManifestError, match="entity-OrgTeam-SOP"):
        load_manifest(dest)


def test_missing_routing_raises(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    (dest / "entity-Team-Routing.md").unlink()
    with pytest.raises(TeamManifestError, match="entity-Team-Routing"):
        load_manifest(dest)


def test_no_seats_raises(tmp_path: Path) -> None:
    dest = _copy_templates_to(tmp_path)
    for f in dest.glob("entity-seat-*.md"):
        f.unlink()
    with pytest.raises(TeamManifestError, match="no entity-seat"):
        load_manifest(dest)


def test_empty_source_dir_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(TeamManifestError):
        load_manifest(empty)


def test_missing_source_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(TeamManifestError):
        load_manifest(tmp_path / "does-not-exist")
