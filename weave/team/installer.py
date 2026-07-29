"""install_team(target_vault, subdir='entities', force=False).

Materializes the in-repo team templates into a target vault THROUGH
WeaveCore.create — never a raw filesystem copy — so overwrites route
through the hardened tombstone path and `force=False` refuses to clobber
an existing file (matches the WeaveCore.create(overwrite=False) contract).

This is the ONLY path in the team engine that ever writes into a vault.
It is an explicit opt-in step: `team install --vault PATH`. Tests always
target a tempfile.mkdtemp() vault; SC's live vault is only touched if he
runs this command against it himself.
"""

from __future__ import annotations

from pathlib import Path

from ..core import WeaveCore
from ..vault import Vault
from .loader import TEMPLATES_DIR


def install_team(target_vault: Vault, subdir: str = "entities", force: bool = False) -> list[str]:
    """Write every team template into `target_vault` under `subdir`.

    Returns the list of vault-relative paths written. Raises
    FileExistsError (propagated from WeaveCore.create) on the first
    already-present file when force=False.
    """
    core = WeaveCore(target_vault)
    written: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.md")):
        rel_in_templates = path.relative_to(TEMPLATES_DIR).as_posix()
        dest_rel = f"{subdir}/{rel_in_templates}" if subdir else rel_in_templates
        content = path.read_text(encoding="utf-8")
        core.create(dest_rel, content, overwrite=force)
        written.append(dest_rel)
    return written


def missing_team_files(target_vault: Vault, subdir: str = "entities") -> list[str]:
    """Return vault-relative paths of team templates NOT yet present in `target_vault`.

    Pure read-only probe — does not write anything. Used to drive idempotent
    repair (install only what's absent) instead of the all-or-nothing
    force=True/False choice in install_team.
    """
    missing: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.md")):
        rel_in_templates = path.relative_to(TEMPLATES_DIR).as_posix()
        dest_rel = f"{subdir}/{rel_in_templates}" if subdir else rel_in_templates
        if not target_vault.exists(dest_rel):
            missing.append(dest_rel)
    return missing


def repair_team(target_vault: Vault, subdir: str = "entities") -> list[str]:
    """Idempotent repair: create ONLY the team template files absent from
    `target_vault`, leaving every existing file untouched (no tombstoning,
    no FileExistsError). Returns the list of vault-relative paths written.

    This is the safe counterpart to install_team(force=True): a partial or
    interrupted install can be healed without clobbering good files.
    """
    core = WeaveCore(target_vault)
    written: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.md")):
        rel_in_templates = path.relative_to(TEMPLATES_DIR).as_posix()
        dest_rel = f"{subdir}/{rel_in_templates}" if subdir else rel_in_templates
        if target_vault.exists(dest_rel):
            continue
        content = path.read_text(encoding="utf-8")
        core.create(dest_rel, content, overwrite=False)
        written.append(dest_rel)
    return written


__all__ = ["install_team", "missing_team_files", "repair_team"]
