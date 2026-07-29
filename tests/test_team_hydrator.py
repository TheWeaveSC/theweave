"""Hydrate output shape + determinism tests."""

from __future__ import annotations

from weave.team.hydrator import hydrate
from weave.team.loader import load_manifest
from weave.team.models import CANONICAL_HARD_FLOORS, CANONICAL_LOOP_PHASES


def test_hydrate_nonempty() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    assert rendered.strip()


def test_hydrate_contains_every_seat_name() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    for seat in manifest.seats:
        assert seat.name in rendered


def test_hydrate_contains_all_six_canonical_phase_names() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    for phase_name in CANONICAL_LOOP_PHASES:
        assert phase_name in rendered


def test_hydrate_contains_cross_attack_and_reproduce() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    assert "cross-attack" in rendered
    assert "reproduce" in rendered


def test_hydrate_contains_all_five_hard_floor_strings() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    for floor in CANONICAL_HARD_FLOORS:
        assert floor in rendered


def test_hydrate_contains_routing_table() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    assert "Routing policy" in rendered
    assert "claude-haiku" in rendered
    assert "claude-sonnet-5" in rendered
    assert "claude-opus" in rendered


def test_hydrate_contains_chairman_lane_constraint() -> None:
    manifest = load_manifest()
    rendered = hydrate(manifest)
    assert "never IC" in rendered or "never build" in rendered


def test_hydrate_output_deterministic_across_calls() -> None:
    manifest = load_manifest()
    first = hydrate(manifest)
    second = hydrate(manifest)
    assert first == second


def test_hydrate_deterministic_across_fresh_loads() -> None:
    first = hydrate(load_manifest())
    second = hydrate(load_manifest())
    assert first == second
