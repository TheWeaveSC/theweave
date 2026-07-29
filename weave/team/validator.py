"""validate_team(source) -> DoctorReport.

"Doctor for the team": reuses doctor.CheckGroup/DoctorReport so `weave-cli
team validate` prints and exit-codes exactly like `weave-cli doctor`.
"""

from __future__ import annotations

from ..doctor import FAIL, INFO, PASS, CheckGroup, DoctorReport
from .hydrator import hydrate
from .loader import load_manifest
from .models import (
    CANONICAL_HARD_FLOORS,
    CANONICAL_LOOP_PHASES,
    TeamManifestError,
    Tier,
)


def validate_team(source=None) -> DoctorReport:
    g = CheckGroup("Team")

    try:
        manifest = load_manifest(source)
    except TeamManifestError as e:
        g.add("manifest", FAIL, f"Manifest failed to load: {e}")
        return DoctorReport(groups=[g])
    g.add("manifest", PASS, f"Manifest loaded: {len(manifest.seats)} seat(s)")

    # Every seat has a tier, and it's a real Tier.
    bad_seats = [s.name for s in manifest.seats if not isinstance(s.default_tier, Tier)]
    if bad_seats:
        g.add("seat-tiers", FAIL, f"Seat(s) with invalid tier: {bad_seats}")
    else:
        g.add("seat-tiers", PASS, "All seats have a valid tier")

    # Every model_seat tier resolves to a real model id.
    bad_models = []
    for s in manifest.seats:
        try:
            _ = s.default_tier.model_id
        except Exception:
            bad_models.append(s.name)
    if bad_models:
        g.add("tier-models", FAIL, f"Seat(s) whose tier has no model id: {bad_models}")
    else:
        g.add("tier-models", PASS, "Every seat tier resolves to a model id")

    # Hard floors present and non-empty, matches canonical set.
    if not manifest.hard_floors:
        g.add("hard-floors", FAIL, "hard_floors is empty")
    elif set(manifest.hard_floors) != set(CANONICAL_HARD_FLOORS):
        g.add("hard-floors", FAIL,
              f"hard_floors mismatch — expected {sorted(CANONICAL_HARD_FLOORS)}, "
              f"got {sorted(manifest.hard_floors)}")
    else:
        g.add("hard-floors", PASS, f"{len(manifest.hard_floors)} hard-floor invariant(s) present")

    # Loop phases cover the canonical six.
    phase_names = {p.name for p in manifest.loop_phases}
    missing_phases = set(CANONICAL_LOOP_PHASES) - phase_names
    if missing_phases:
        g.add("loop-phases", FAIL, f"Missing canonical loop phase(s): {sorted(missing_phases)}")
    else:
        g.add("loop-phases", PASS, f"All {len(CANONICAL_LOOP_PHASES)} canonical loop phases present")

    # hydrate() produces non-empty output.
    try:
        rendered = hydrate(manifest)
        if not rendered.strip():
            g.add("hydrate", FAIL, "hydrate() produced empty output")
        else:
            g.add("hydrate", PASS, f"hydrate() produced {len(rendered)} chars")
    except Exception as e:
        g.add("hydrate", FAIL, f"hydrate() raised: {type(e).__name__}: {e}")

    g.add("champion", INFO, f"governance_champion: {manifest.governance_champion or '(unset)'}")

    return DoctorReport(groups=[g])


__all__ = ["validate_team"]
