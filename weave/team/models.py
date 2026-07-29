"""Frozen dataclasses for the Org Team Engine.

Pure data + light invariant checks. No I/O here — loader.py is the only
module that touches the filesystem/vault to build these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """Difficulty tier -> model id. Renaming a model is a one-line change
    here; nothing else in the engine hardcodes a model string.
    """

    MECHANICAL = "mechanical"
    STANDARD = "standard"
    HARD = "hard"

    @property
    def model_id(self) -> str:
        return _TIER_MODEL_IDS[self]

    @classmethod
    def from_str(cls, value: str) -> "Tier":
        v = (value or "").strip().lower()
        try:
            return cls(v)
        except ValueError as e:
            raise TeamManifestError(f"unknown tier: {value!r} (expected one of "
                                     f"{[t.value for t in Tier]})") from e


_TIER_MODEL_IDS: dict[Tier, str] = {
    Tier.MECHANICAL: "claude-haiku",
    Tier.STANDARD: "claude-sonnet-5",
    Tier.HARD: "claude-opus",
}

DEFAULT_TIER = Tier.STANDARD

# Canonical six-phase loop, in order. Kept here (not just in the template)
# so validator/hydrator can assert coverage without re-parsing markdown.
CANONICAL_LOOP_PHASES: tuple[str, ...] = (
    "Intake",
    "Plan",
    "Execute",
    "GovernanceGate",
    "Converge",
    "Settle",
)

CANONICAL_HARD_FLOORS: tuple[str, ...] = (
    "verify-artefact-not-self-report",
    "verify-against-users-own-tool",
    "spec-strict-output",
    "fact-source-accuracy",
    "lease-safety",
)


class TeamManifestError(ValueError):
    """Raised when team template/vault data fails to parse or validate."""


@dataclass(frozen=True)
class Seat:
    """One roster seat."""

    name: str                      # seat_name, e.g. "Lucky"
    role: str
    roster: str                    # "build-org" | "air" | ...
    persona: str                   # short persona summary (from body)
    capabilities: tuple[str, ...]
    default_tier: Tier
    when_to_use: str
    rel_path: str = ""             # source file, for error messages

    def __post_init__(self) -> None:
        if not self.name:
            raise TeamManifestError(f"seat at {self.rel_path!r} has empty name")
        if not isinstance(self.default_tier, Tier):
            raise TeamManifestError(
                f"seat {self.name!r} at {self.rel_path!r} has non-Tier default_tier: "
                f"{self.default_tier!r}"
            )


@dataclass(frozen=True)
class LoopPhase:
    """One phase of the governance loop."""

    name: str
    mechanic: str
    notes: str = ""


@dataclass(frozen=True)
class RoutingPolicy:
    """Difficulty -> tier routing policy, as structured data."""

    tiers: dict[str, str]                  # label -> tier value, e.g. {"mechanical": "haiku", ...}
    default_tier: Tier
    mechanical_cues: tuple[str, ...] = (
        "edit", "grep", "fixture", "rename", "single-string edit",
    )
    hard_cues: tuple[str, ...] = (
        "adversarial", "gate", "judge", "design", "synthesis", "reproduce",
    )


@dataclass(frozen=True)
class TeamManifest:
    """The whole team-as-data graph, loaded and validated."""

    hub_version: int
    seats: tuple[Seat, ...]
    loop_phases: tuple[LoopPhase, ...]
    hard_floors: tuple[str, ...]
    routing_policy: RoutingPolicy
    governance_champion: str = ""

    def __post_init__(self) -> None:
        if not self.seats:
            raise TeamManifestError("manifest has zero seats")
        names = [s.name for s in self.seats]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise TeamManifestError(f"duplicate seat name(s) in manifest: {dupes}")

    def seat(self, name: str) -> Seat | None:
        for s in self.seats:
            if s.name == name:
                return s
        return None


__all__ = [
    "Tier",
    "DEFAULT_TIER",
    "CANONICAL_LOOP_PHASES",
    "CANONICAL_HARD_FLOORS",
    "TeamManifestError",
    "Seat",
    "LoopPhase",
    "RoutingPolicy",
    "TeamManifest",
]
