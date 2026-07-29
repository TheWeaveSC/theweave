"""Table-driven routing tests — seat defaults, overrides, cue words."""

from __future__ import annotations

import pytest

from weave.team.loader import load_manifest
from weave.team.models import Tier
from weave.team.routing import route


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


# ---------- seat defaults resolve ----------

@pytest.mark.parametrize("seat_name,expected_tier", [
    ("Sonnet", Tier.HARD),
    ("Director", Tier.HARD),
    ("Lucky", Tier.STANDARD),
    ("Clutch", Tier.STANDARD),
    ("Diamond", Tier.STANDARD),
    ("Coco", Tier.STANDARD),
    ("Sterling", Tier.STANDARD),
    ("Watchdog", Tier.STANDARD),
    ("Timmy", Tier.MECHANICAL),
])
def test_seat_default_resolves(manifest, seat_name, expected_tier) -> None:
    seat = manifest.seat(seat_name)
    assert seat is not None
    assert route(seat) == expected_tier


# ---------- explicit override beats default ----------

def test_explicit_override_beats_seat_default(manifest) -> None:
    seat = manifest.seat("Timmy")  # default MECHANICAL
    assert route(seat, task_difficulty="hard") == Tier.HARD


def test_explicit_override_accepts_tier_enum(manifest) -> None:
    seat = manifest.seat("Sonnet")  # default HARD
    assert route(seat, task_difficulty=Tier.MECHANICAL) == Tier.MECHANICAL


# ---------- cue words beat a STANDARD default ----------

@pytest.mark.parametrize("task_text", [
    "please apply this single-string edit to config.py",
    "run a quick grep for the old function name",
    "fix the broken test fixture",
    "rename this variable everywhere",
])
def test_mechanical_cue_words_beat_standard_default(manifest, task_text) -> None:
    seat = manifest.seat("Lucky")  # default STANDARD
    assert route(seat, task_text=task_text) == Tier.MECHANICAL


@pytest.mark.parametrize("task_text", [
    "run an adversarial verify pass on this PR",
    "this needs a design review before we ship",
    "final synthesis of the council's findings",
    "reproduce the failure on the real tool",
    "judge the two candidate proposals",
    "hold the governance gate on this",
])
def test_hard_cue_words_beat_standard_default(manifest, task_text) -> None:
    seat = manifest.seat("Clutch")  # default STANDARD
    assert route(seat, task_text=task_text) == Tier.HARD


# ---------- worked example from the routing policy doc ----------

def test_lucky_single_string_edit_does_not_change_seat_default(manifest) -> None:
    seat = manifest.seat("Lucky")
    assert seat.default_tier == Tier.STANDARD
    # One cued task resolves to MECHANICAL...
    assert route(seat, task_text="apply this single-string edit") == Tier.MECHANICAL
    # ...but the seat's own default is untouched, and the next uncued task
    # for Lucky still resolves to STANDARD.
    assert seat.default_tier == Tier.STANDARD
    assert route(seat, task_text="") == Tier.STANDARD


# ---------- empty task on STANDARD seat stays STANDARD ----------

def test_empty_task_text_on_standard_seat_stays_standard(manifest) -> None:
    seat = manifest.seat("Diamond")
    assert route(seat, task_text="") == Tier.STANDARD


def test_no_seat_no_task_falls_back_to_engine_default() -> None:
    assert route(None) == Tier.STANDARD


# ---------- every Tier maps to a non-empty model id ----------

@pytest.mark.parametrize("tier", list(Tier))
def test_every_tier_has_nonempty_model_id(tier) -> None:
    assert tier.model_id
    assert isinstance(tier.model_id, str)


def test_tier_from_str_roundtrips() -> None:
    assert Tier.from_str("hard") == Tier.HARD
    assert Tier.from_str("STANDARD") == Tier.STANDARD
    assert Tier.from_str(" mechanical ") == Tier.MECHANICAL


def test_tier_from_str_rejects_unknown() -> None:
    from weave.team.models import TeamManifestError
    with pytest.raises(TeamManifestError):
        Tier.from_str("ultra-mega-tier")
