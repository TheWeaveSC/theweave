"""Audit R1 — bridge-file quarantine + build-time bridge detector.

The quarantined files carry a pseudonym<->real-name crosswalk in their
CONTENT; lane routing alone cannot contain them (they are legitimately
operational-laned, and the ops lane is exactly where an ops-hat query would
find them). Quarantine = never embedded, never PPR-seeded, never returned
from recall in ANY lane. Vault files stay untouched.

Fixture stand-ins are fully synthetic (fictional cast, invented dates) and
live at the rel_paths ruled in the repo-root lane_map.yaml demo seed, so
exact-path quarantine and the vocab detector are both exercised with zero
real vault content.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from weave.vault import Note, Vault
from weave.pro import cortex as cx
from weave.pro.dense import (DENSE_DB, detect_bridge_files, quarantined_files,
                             unretrievable_files)
from weave.pro.embedder import FakeEmbedder
from weave.pro.recall import recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "lane-vault"

QUARANTINED_REL = ("HomeVault/entities/entity-DanaVo.md", "wiki/people/Dana.md",
                   "HomeVault/entities/entity-AtlasERP.md",
                   "HomeVault/entities/entity-Mira.md",
                   # Consolidation rollups aggregate cross-lane content and
                   # grow into heavily linked PPR hubs; the signals file's
                   # identity-scoping section pairs both vocab lists in one
                   # text. All are quarantined by exact path.
                   "_archive/consolidation-2025-04-05-1330.md",
                   "_archive/consolidation-2025-05-01-0800.md",
                   "LearningLayer/signals-2025-04-02.md",
                   # Same-day revisions of the -1330 dump carry byte-similar
                   # crosswalk sentences — quarantined as a family.
                   "_archive/consolidation-2025-04-05-0910.md",
                   "_archive/consolidation-2025-04-05-1120.md",
                   # A quarantine ruling may pin a path with no file on disk
                   # (the seed documents this pattern). Keep pin and lane_map
                   # entry in sync: a pin that lags the lane_map entry is a
                   # confidentiality guard failing silently. No fixture
                   # stand-in exists for this path, so only the pin is
                   # exercised, not the retrieval behaviour.
                   "LearningLayer/signals-2025-05-06-lane-review-notes.md")
QUARANTINED_NAMES = {"entity-DanaVo", "Dana", "entity-AtlasERP", "entity-Mira",
                     "consolidation-2025-04-05-1330",
                     "consolidation-2025-05-01-0800", "signals-2025-04-02",
                     "consolidation-2025-04-05-0910",
                     "consolidation-2025-04-05-1120",
                     "signals-2025-05-06-lane-review-notes"}

# Adversarial leak queries: each names quarantined content directly.
LEAK_QUERIES = [
    "what is Dana's thesis pseudonym",
    "what is Atlas's thesis case pseudonym Firm Alpha",
    "who is the logistics lead real identity",
    "Mira site scheduling function thesis anonymised name",
    "Northwind Power Group retired pseudonym Firm Beta",
]

# Proof queries targeting the consolidation rollups and the identity-scoping
# signals file, in both lanes.
PROOF_QUERIES = [
    ("operational", "Northwind Power Group retired pseudonym Firm Beta"),
    ("thesis", "Northwind Power Group retired pseudonym Firm Beta"),
    ("operational", "consolidation dump entity overview"),
    ("thesis", "consolidation dump entity overview"),
    # the same-day revision family
    ("operational", "consolidation entity overview April 5"),
    ("thesis", "consolidation entity overview April 5"),
]


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    return Vault(vroot)


@pytest.fixture
def built_vault(vault) -> Vault:
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    return vault


def test_quarantine_fixture_files_present():
    """Anti-vacuity gate: every quarantined path EXCEPT the documented
    no-fixture pin must exist in the committed fixture vault. A clone where
    these files are missing (e.g. swallowed by a gitignore rule) would make
    every retrieval assertion below pass vacuously — fail loudly instead."""
    no_fixture = {"LearningLayer/signals-2025-05-06-lane-review-notes.md"}
    missing = [rel for rel in QUARANTINED_REL
               if rel not in no_fixture and not (FIXTURE_VAULT / rel).is_file()]
    assert missing == [], \
        f"quarantine fixture files missing from the checkout: {missing}"


def test_quarantine_list_pins():
    assert set(quarantined_files()) == set(QUARANTINED_REL)
    # quarantine is part of the never-retrieve set alongside the hubs
    assert set(QUARANTINED_REL) <= set(unretrievable_files())


def test_quarantined_never_embedded(built_vault):
    db_path = cx.cortex_dir(built_vault) / DENSE_DB
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ph = ",".join("?" * len(QUARANTINED_REL))
        n = db.execute(f"SELECT COUNT(*) FROM chunks WHERE rel_path IN ({ph})",
                       QUARANTINED_REL).fetchone()[0]
        assert n == 0, f"quarantined files produced {n} chunk rows"
    finally:
        db.close()


def test_leak_queries_zero_quarantined_hits_any_lane(built_vault):
    """The adversarial leak queries: zero quarantined-file names in results
    at any rank, in ANY lane — and never in the seeds either."""
    for lane in ("thesis", "operational", "neutral"):
        for q in LEAK_QUERIES:
            r = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane=lane)
            assert not r.degraded
            got = {h.note_name for h in r.hits}
            assert not got & QUARANTINED_NAMES, \
                f"quarantined file returned (lane={lane}, q={q!r}): {got & QUARANTINED_NAMES}"
            assert not set(r.seeds) & QUARANTINED_NAMES, \
                f"quarantined file seeded (lane={lane}, q={q!r})"


def test_quarantined_never_seeded_even_when_named(built_vault):
    """'Dana' is a direct entity-name match for the wiki stand-in — without
    quarantine it WOULD seed (the classic rank-1 leak mechanism)."""
    r = recall(built_vault, "what is Dana's thesis pseudonym", k=100,
               embedder=FakeEmbedder(), lane="operational")
    assert "Dana" not in r.seeds and "entity-DanaVo" not in r.seeds


def test_proof_queries_zero_quarantined_any_lane(built_vault):
    """Proof queries against the quarantined rollups and the identity-scoping
    signals stand-in: zero quarantined names in hits or seeds at any rank.
    The mega-hub consolidation stand-in is deliberately well-linked (graph
    node with cross-lane edges) so PPR mass alone must not surface it."""
    for lane, q in PROOF_QUERIES:
        r = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane=lane)
        assert not r.degraded
        got = {h.note_name for h in r.hits}
        assert not got & QUARANTINED_NAMES, \
            f"quarantined file returned (lane={lane}, q={q!r}): {got & QUARANTINED_NAMES}"
        assert not set(r.seeds) & QUARANTINED_NAMES, \
            f"quarantined file seeded (lane={lane}, q={q!r})"


# ---------------------------------------------------------------------------
# Build-time bridge detector (R1b)
# ---------------------------------------------------------------------------


def _fake_note(rel: str, raw: str) -> Note:
    return Note(path=Path("/x") / rel, rel_path=rel, name=Path(rel).stem,
                metadata={}, content=raw, raw_text=raw)


def test_detector_flags_both_vocab_unruled_note():
    hits = detect_bridge_files([
        _fake_note("HomeVault/sessions/2025-05-10-new-bridge.md",
                   "Turns out Firm Alpha is really Atlas under the hood."),
        _fake_note("HomeVault/sessions/2025-05-10-pseud-only.md",
                   "Firm Beta milestones reviewed."),           # one list only
        _fake_note("HomeVault/sessions/2025-05-10-real-only.md",
                   "Westgate turbine layout memo."),            # one list only
        _fake_note("HomeVault/sessions/2025-05-10-neither.md",
                   "Generic note about nothing sensitive."),
    ])
    assert hits == ["HomeVault/sessions/2025-05-10-new-bridge.md"]


def test_detector_skips_ruled_and_quarantined():
    hits = detect_bridge_files([
        # quarantined: matches both vocabs but must NOT be flagged
        _fake_note("HomeVault/entities/entity-DanaVo.md",
                   "Dana is the Logistics Lead of Firm Beta."),
        # explicitly ruled (thesis hot file): matches both, not flagged
        _fake_note("HomeVault/Draft Manuscript.md",
                   "Firm Beta was formerly Northwind Power; site is Westgate."),
    ])
    assert hits == []


def test_detector_matches_identity_scoping_pattern():
    """Multi-word vocab phrases hemmed by slashes, equals signs, and sentence
    punctuation MUST match — a matcher that only handles clean word
    boundaries misses exactly the shape identity-scoping notes take.
    (Synthetic text only; no real pseudonym<->real-name mapping is stated.)"""
    hits = detect_bridge_files([
        _fake_note(
            "LearningLayer/signals-2025-03-15-identity-scoping-standin.md",
            "## Identity-scoping signal (stand-in)\n"
            "NW-Group / Northwind Power Group = retired alias for "
            "Firm Beta, used only in drafts. Elsewhere: Summit Energy "
            "is a client group term.\n"),
    ])
    assert hits == ["LearningLayer/signals-2025-03-15-identity-scoping-standin.md"]


def test_rebuild_emits_truncation_proof_summary(vault):
    """The FINAL build log line restates the detector verdict, so a `tail`
    of the log can never silently swallow the per-file warnings."""
    logs: list[str] = []
    cx.rebuild(vault, embedder=FakeEmbedder(), log=logs.append)
    assert "bridge detector: 0 files flagged" in logs[-1]

    bridge_rel = "HomeVault/sessions/2025-05-12-bridge-standin.md"
    (vault.root / bridge_rel).write_text(
        "---\ntype: session\n---\n# Standin\nFirm Alpha next to Atlas.\n",
        encoding="utf-8")
    logs2: list[str] = []
    cx.rebuild(vault, embedder=FakeEmbedder(), log=logs2.append,
               allow_unruled_bridges=True)
    assert "1 file(s) flagged" in logs2[-1], \
        f"final line must carry the flag count, got: {logs2[-1]!r}"


def test_rebuild_warns_loudly_on_bridge_file(vault):
    """End-to-end (override path): an unruled both-vocab note makes rebuild
    emit a LOUD warning naming the file; the quarantined stand-ins (which
    also match both vocabs) stay silent because they are already handled."""
    bridge_rel = "HomeVault/sessions/2025-05-11-omega-dossier.md"
    (vault.root / bridge_rel).write_text(
        "---\ntype: session\n---\n# Dossier\n"
        "Firm Alpha in the study is Atlas; Summit Energy is the parent.\n",
        encoding="utf-8")
    logs: list[str] = []
    cx.rebuild(vault, embedder=FakeEmbedder(), log=logs.append,
               allow_unruled_bridges=True)
    warnings = [l for l in logs if l.startswith("⚠ BRIDGE-FILE WARNING")]
    assert len(warnings) == 1, f"expected exactly one bridge warning, got {warnings}"
    assert bridge_rel in warnings[0]
    assert "entity-DanaVo" not in " ".join(warnings)


def test_rebuild_fails_closed_on_unruled_bridge(vault, tmp_path, monkeypatch):
    """Audit H1 — vocab-edit forcing function. Default rebuild REFUSES
    (nothing written) when the detector finds an unruled bridge file; the
    override proceeds with warnings; ruling the file in lane_map gives a
    clean pass."""
    import yaml as _yaml
    from weave.pro import dense as _dense
    from weave.pro.cortex import BridgeFilesUnruled

    bridge_rel = "HomeVault/sessions/2025-05-13-unruled-bridge.md"
    (vault.root / bridge_rel).write_text(
        "---\ntype: session\n---\n# Unruled\nFirm Beta beside Westgate.\n",
        encoding="utf-8")

    # 1. default: fail closed, message names the file, nothing written
    with pytest.raises(BridgeFilesUnruled, match="2025-05-13-unruled-bridge"):
        cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    assert not (cx.cortex_dir(vault) / "manifest.json").exists(), \
        "refused build must not write a manifest"

    # 2. explicit override: proceeds, loud warning present
    logs: list[str] = []
    st = cx.rebuild(vault, embedder=FakeEmbedder(), log=logs.append,
                    allow_unruled_bridges=True)
    assert st.fresh
    assert any(bridge_rel in l for l in logs if "BRIDGE-FILE WARNING" in l)

    # 3. rule the file in lane_map (private copy) -> clean default pass
    lm_copy = tmp_path / "lane_map.yaml"
    raw = _yaml.safe_load(_dense.LANE_MAP_FILE.read_text(encoding="utf-8"))
    raw["lanes"]["operational"]["explicit_files"].append(bridge_rel)
    lm_copy.write_text(_yaml.dump(raw), encoding="utf-8")
    monkeypatch.setattr(_dense, "LANE_MAP_FILE", lm_copy)
    logs3: list[str] = []
    st3 = cx.rebuild(vault, embedder=FakeEmbedder(), log=logs3.append)
    assert st3.fresh
    assert "bridge detector: 0 files flagged" in logs3[-1]
