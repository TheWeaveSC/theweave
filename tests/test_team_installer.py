"""Installer round-trip tests — always against a tmp_path vault, never live."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from weave.team.installer import install_team
from weave.team.loader import TEMPLATES_DIR, load_manifest
from weave.vault import Vault
from weave.vault import VaultConflictError  # noqa: F401  (sanity: hardened path importable)


def _tmp_vault() -> tuple[Path, Vault]:
    root = Path(tempfile.mkdtemp())
    return root, Vault(root)


def test_install_writes_expected_rel_paths() -> None:
    root, vault = _tmp_vault()
    written = install_team(vault)
    expected = {f"entities/{p.name}" for p in TEMPLATES_DIR.glob("*.md")}
    assert set(written) == expected
    for rel in written:
        assert (root / rel).is_file()


def test_install_round_trips_with_loader() -> None:
    root, vault = _tmp_vault()
    install_team(vault)
    from_templates = load_manifest()
    from_vault = load_manifest(vault)

    assert {s.name for s in from_templates.seats} == {s.name for s in from_vault.seats}
    assert from_templates.hub_version == from_vault.hub_version
    assert set(from_templates.hard_floors) == set(from_vault.hard_floors)
    assert {p.name for p in from_templates.loop_phases} == {p.name for p in from_vault.loop_phases}
    for name in {s.name for s in from_templates.seats}:
        a = from_templates.seat(name)
        b = from_vault.seat(name)
        assert a.role == b.role
        assert a.default_tier == b.default_tier
        assert a.roster == b.roster


def test_reinstall_default_no_force_raises_file_exists() -> None:
    root, vault = _tmp_vault()
    install_team(vault)
    with pytest.raises(FileExistsError):
        install_team(vault, force=False)


def test_reinstall_with_force_tombstones_prior_file() -> None:
    root, vault = _tmp_vault()
    install_team(vault)
    trash_dir = root / ".trash"
    assert not trash_dir.exists()

    install_team(vault, force=True)

    assert trash_dir.is_dir()
    tombstoned = list(trash_dir.glob("*.md"))
    # One tombstone per file that got overwritten.
    n_templates = len(list(TEMPLATES_DIR.glob("*.md")))
    assert len(tombstoned) == n_templates


def test_install_custom_subdir() -> None:
    root, vault = _tmp_vault()
    written = install_team(vault, subdir="team-entities")
    assert all(rel.startswith("team-entities/") for rel in written)
    assert (root / "team-entities").is_dir()


def test_install_empty_subdir_writes_to_vault_root() -> None:
    root, vault = _tmp_vault()
    written = install_team(vault, subdir="")
    assert all("/" not in rel for rel in written)
    for rel in written:
        assert (root / rel).is_file()
