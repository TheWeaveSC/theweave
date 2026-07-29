"""L4 — the one-click installer: `weave-cli init`.

Thin orchestrator over existing, already-hardened pieces (WeaveCore,
Vault, install_team, run_doctor, validate_team). See init.py for the
InstallPlan / run_init() entry point and config.py for the Claude
config wiring test seam.
"""

from .init import InstallOptions, InstallPlan, run_init

__all__ = ["InstallOptions", "InstallPlan", "run_init"]
