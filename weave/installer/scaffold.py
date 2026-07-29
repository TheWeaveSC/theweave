"""Generic vault scaffold — dirs + BOOT.md + entities/index.md + seed signal.

Reads from templates/vault/ (versioned, generic, zero personal content).
Writes go through Vault._atomic_write / write_text_tombstoning_prior so
every scaffold write is atomic and every overwrite is tombstoned, exactly
like the rest of the write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from ..vault import Vault

TEMPLATES_VAULT_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "vault"

# Directory skeleton every scaffolded vault gets, independent of whether
# the team install adds more nested dirs under entities/.
SCAFFOLD_DIRS: tuple[str, ...] = ("entities", "LearningLayer", "sessions")


@dataclass(frozen=True)
class BootFileSpec:
    """One generic boot/index/signal file to materialize into the vault."""

    template_rel: str   # path under templates/vault/
    dest_rel: str        # vault-relative destination (may differ, e.g. seed signal renamed by month)
    render: bool = False  # whether to .format(month=..., date=...) the template


def _today() -> _date:
    return _date.today()


def boot_file_specs(today: _date | None = None) -> list[BootFileSpec]:
    d = today or _today()
    month = d.strftime("%Y-%m")
    signal_dest = f"LearningLayer/signals-{month}-init.md"
    return [
        BootFileSpec("BOOT.md", "BOOT.md", render=False),
        BootFileSpec("entities/index.md", "entities/index.md", render=False),
        BootFileSpec("LearningLayer/signals-init.md", signal_dest, render=True),
    ]


def render_boot_file(template_rel: str, today: _date | None = None) -> str:
    d = today or _today()
    text = (TEMPLATES_VAULT_DIR / template_rel).read_text(encoding="utf-8")
    return text.format(month=d.strftime("%Y-%m"), date=d.isoformat())


def scaffold_status(vault_root: Path, today: _date | None = None) -> dict[str, str]:
    """Idempotency probe: for each dir and boot file, what WOULD happen.

    Returns {rel_path: "create" | "skip-exists"}. Pure inspection, no writes.
    """
    status: dict[str, str] = {}
    for d in SCAFFOLD_DIRS:
        status[f"{d}/"] = "skip-exists" if (vault_root / d).is_dir() else "create"
    for spec in boot_file_specs(today):
        status[spec.dest_rel] = "skip-exists" if (vault_root / spec.dest_rel).exists() else "create"
    return status


def apply_scaffold(vault: Vault, force: bool = False, today: _date | None = None) -> list[str]:
    """Create the dir skeleton + write boot files. Returns rel paths actually written.

    Dirs are always mkdir(exist_ok=True) — never an error, never "clobbered"
    (a directory has no content to lose). Boot files default to skip-exists
    (never overwrite user edits); force=True promotes existing files to a
    tombstoning overwrite.
    """
    written: list[str] = []
    for d in SCAFFOLD_DIRS:
        (vault.root / d).mkdir(parents=True, exist_ok=True)

    for spec in boot_file_specs(today):
        dest_abs = vault.root / spec.dest_rel
        content = render_boot_file(spec.template_rel, today) if spec.render else \
            (TEMPLATES_VAULT_DIR / spec.template_rel).read_text(encoding="utf-8")
        if dest_abs.exists() and not force:
            continue
        if dest_abs.exists():
            vault.write_text_tombstoning_prior(spec.dest_rel, content)
        else:
            vault.write_text(spec.dest_rel, content)
        written.append(spec.dest_rel)

    return written


__all__ = [
    "TEMPLATES_VAULT_DIR",
    "SCAFFOLD_DIRS",
    "BootFileSpec",
    "boot_file_specs",
    "render_boot_file",
    "scaffold_status",
    "apply_scaffold",
]
