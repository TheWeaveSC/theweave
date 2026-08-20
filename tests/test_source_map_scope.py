"""v0.5 item 18 — what source_map() hashes, and what it must not.

Quarantined files feed ZERO artifacts (graphrep drops them as nodes,
dense_eligible refuses them), so editing one used to flip the entire cortex
STALE while not a byte of dense.sqlite3 or graph.json could change.

The scope is deliberately narrow. `unretrievable_files()` = hub exclusions ∪
quarantine, and the hub exclusions are dropped from the DENSE index but remain
graph nodes — their content still feeds graph.json, so they must keep
invalidating the cache. Using the wider set here would have been a real bug.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro.cortex import source_map
from weave.pro.dense import quarantined_files, unretrievable_files

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "lane-vault"


@pytest.fixture
def vault(tmp_path) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    return Vault(vroot)


def test_quarantined_files_are_not_hashed(vault):
    sm = source_map(vault)
    present = {q for q in quarantined_files() if (vault.root / q).exists()}
    assert present, "fixture must contain quarantined stand-ins or this proves nothing"
    assert not (present & set(sm))


def test_editing_a_quarantined_file_does_not_flip_staleness(vault):
    before = source_map(vault)
    target = next(q for q in quarantined_files() if (vault.root / q).exists())
    p = vault.root / target
    p.write_text(p.read_text(encoding="utf-8") + "\n\nappended.\n", encoding="utf-8")
    assert source_map(vault) == before


def test_hub_excluded_files_STILL_invalidate(vault):
    """The narrowness of the scope, pinned. BOOT.md is dense-excluded
    but is still a graph node, so its content feeds an artifact."""
    hub_only = (set(unretrievable_files()) - set(quarantined_files()))
    target = next((h for h in hub_only if (vault.root / h).exists()), None)
    assert target, "fixture must contain a hub-excluded, non-quarantined file"

    before = source_map(vault)
    assert target in before, "hub-excluded files must still be hashed"
    p = vault.root / target
    p.write_text(p.read_text(encoding="utf-8") + "\n\nappended.\n", encoding="utf-8")
    assert source_map(vault) != before


def test_snapshot_and_raw_forms_agree(vault):
    """THE consistency invariant. rebuild() builds the manifest from the
    snapshot form; verify_fresh() compares against the raw form. If the two
    ever disagree the cortex is stale the instant it is built."""
    notes = vault.iter_notes_sorted()
    assert source_map(vault) == source_map(vault, notes)
