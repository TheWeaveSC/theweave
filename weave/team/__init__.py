"""The Org Team Engine — team-as-data, difficulty->model routing, and
arm-on-connect hydration, powered by Weave.

Standalone: imports only from within `weave/` (Vault, WeaveCore, doctor's
report types). No dependency on any sibling app.
"""

from __future__ import annotations

from .hydrator import hydrate
from .installer import install_team
from .loader import load_manifest
from .models import (
    CANONICAL_HARD_FLOORS,
    CANONICAL_LOOP_PHASES,
    LoopPhase,
    RoutingPolicy,
    Seat,
    TeamManifest,
    TeamManifestError,
    Tier,
)
from .routing import route
from .validator import validate_team

__all__ = [
    "hydrate",
    "install_team",
    "load_manifest",
    "route",
    "validate_team",
    "CANONICAL_HARD_FLOORS",
    "CANONICAL_LOOP_PHASES",
    "LoopPhase",
    "RoutingPolicy",
    "Seat",
    "TeamManifest",
    "TeamManifestError",
    "Tier",
]
