"""Item 15 — the read path survives a malformed note.

Regression cover for a live incident class. A single unquoted YAML scalar
containing a colon (`progress: v4.0 LIVE. NEXT PHASE: merge`) in ONE entity
file crashed `frontmatter.loads`, which propagated through `load_note` ->
`iter_notes` -> `iter_notes_sorted` -> `source_map` -> `stale_sources` ->
`verify_fresh`. Because `recall()` calls `_throttled_verify` bare on every
query behind a 20s cache, that takes down LIVE retrieval for a whole
session, not merely the nightly job.

The fix routes freshness through raw bytes (it never needed the parse) and
gives read-path callers a non-raising walk that RETURNS its faults.
"""

from __future__ import annotations

import pytest

from weave.vault import Vault, NoteFault
from weave.pro.cortex import source_map
from weave.pro.ppr import PPRBoot

# The exact defect class from the incident: an unquoted flow scalar whose
# value contains ": ", which YAML reads as a nested mapping.
BAD_FRONTMATTER = (
    "---\n"
    "title: CTL3 FM Rebuild\n"
    "progress: v4.0 CERTIFIED LIVE 2025-06-01. NEXT PHASE: two-entity merge\n"
    "---\n\n"
    "Body text that mentions [[entity-good]].\n"
)
GOOD_NOTE = "---\ntitle: Good\ntype: entity\n---\n\nContent linking [[entity-bad]].\n"


@pytest.fixture
def mixed_vault(tmp_path) -> Vault:
    """A vault with one healthy note and one unparseable note."""
    root = tmp_path / "vault"
    (root / "HomeVault" / "entities").mkdir(parents=True)
    (root / "HomeVault" / "entities" / "entity-good.md").write_text(
        GOOD_NOTE, encoding="utf-8")
    (root / "HomeVault" / "entities" / "entity-bad.md").write_text(
        BAD_FRONTMATTER, encoding="utf-8")
    return Vault(root)


def test_the_bad_note_really_is_unparseable(mixed_vault):
    """Guard the guard: if this fixture ever starts parsing cleanly, every
    other test in this file silently stops testing anything."""
    with pytest.raises(Exception):
        mixed_vault.load_note("HomeVault/entities/entity-bad.md")
    # ...and the strict walk still raises, which is correct for the BUILD path
    with pytest.raises(Exception):
        list(mixed_vault.iter_notes())


def test_source_map_survives_and_hashes_both(mixed_vault):
    """THE regression. source_map is what recall() reaches through
    verify_fresh -> stale_sources on every query."""
    sm = source_map(mixed_vault)
    assert set(sm) == {"HomeVault/entities/entity-good.md",
                       "HomeVault/entities/entity-bad.md"}
    # the malformed file is hashed like any other — it is content, not a hole
    assert all(len(h) == 16 for h in sm.values())


def test_freshness_is_independent_of_parse_success(mixed_vault):
    """Repairing the YAML must change the hash ONLY because the bytes changed.
    Parse success must never be a hidden input to the manifest (audit B2)."""
    before = source_map(mixed_vault)
    bad = mixed_vault.root / "HomeVault" / "entities" / "entity-bad.md"

    # rewrite with identical bytes -> identical hash
    bad.write_text(BAD_FRONTMATTER, encoding="utf-8")
    assert source_map(mixed_vault) == before

    # quote the scalar so it genuinely parses -> hash changes, because the
    # BYTES changed. Not because parseability changed: that is the point.
    repaired = BAD_FRONTMATTER.replace(
        "progress: v4.0 CERTIFIED LIVE 2025-06-01. NEXT PHASE: two-entity merge",
        "progress: 'v4.0 CERTIFIED LIVE 2025-06-01. NEXT PHASE: two-entity merge'")
    bad.write_text(repaired, encoding="utf-8")
    mixed_vault.load_note("HomeVault/entities/entity-bad.md")  # asserts it parses
    assert source_map(mixed_vault) != before


def test_iter_notes_safe_returns_notes_and_faults(mixed_vault):
    notes, faults = mixed_vault.iter_notes_safe()
    assert [n.rel_path for n in notes] == ["HomeVault/entities/entity-good.md"]
    assert len(faults) == 1
    fault = faults[0]
    assert isinstance(fault, NoteFault)
    assert fault.rel_path == "HomeVault/entities/entity-bad.md"
    assert fault.kind == "parse"
    assert fault.error  # non-empty: names the exception, never a bare skip


def test_raw_and_safe_walks_select_the_same_files(mixed_vault):
    """If these two ever diverge, freshness reports phantom added/removed
    entries forever. Both must go through Vault.note_paths()."""
    raw = {rel for rel, _ in mixed_vault.iter_raw_sorted()}
    notes, faults = mixed_vault.iter_notes_safe()
    parsed = {n.rel_path for n in notes} | {f.rel_path for f in faults}
    assert raw == parsed


def test_raw_walk_is_sorted(mixed_vault):
    rels = [rel for rel, _ in mixed_vault.iter_raw_sorted()]
    assert rels == sorted(rels)


def test_degraded_ppr_fallback_does_not_crash(mixed_vault):
    """PPRBoot is what recall() falls back to when the cortex or embedder is
    unavailable. A fallback that dies on a bad note turns a recoverable outage
    into a dead read path."""
    boot = PPRBoot(mixed_vault)
    g = boot.build()
    assert "entity-good" in g.nodes
    assert "entity-bad" not in g.nodes       # unparseable, so not a node
    assert [f.rel_path for f in boot.faults] == [
        "HomeVault/entities/entity-bad.md"]   # and it is REPORTED, not hidden


def test_unreadable_file_yields_a_stable_sentinel(mixed_vault):
    """A file that cannot be decoded must still appear in the map. Vanishing
    would read as 'deleted' and silently drop it from staleness."""
    blob = mixed_vault.root / "HomeVault" / "entities" / "entity-binary.md"
    blob.write_bytes(b"\xff\xfe\x00\x00 not utf-8 \xc3\x28")
    sm1 = source_map(mixed_vault)
    sm2 = source_map(mixed_vault)
    assert "HomeVault/entities/entity-binary.md" in sm1
    assert sm1 == sm2  # stable across calls, so it never looks like churn
