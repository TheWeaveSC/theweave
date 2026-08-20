"""Cortex W1 invariant tests — I1 (cache semantics), I2 (manifest), I3 (never
synced). All offline: FakeEmbedder, tmp cortex base via WEAVE_CORTEX_DIR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro.embedder import FakeEmbedder

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "bench-vault"


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    """Fixture bench-vault copied to tmp (tests may edit it) + isolated cortex base."""
    import shutil
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    return Vault(vroot)


# ---------------------------------------------------------------------------
# I3 — never synced
# ---------------------------------------------------------------------------


def test_cortex_path_outside_vault_tree(vault):
    cdir = cx.cortex_dir(vault)
    with pytest.raises(ValueError):
        cdir.resolve().relative_to(vault.root)  # ValueError = outside = good


def test_cortex_default_path_under_caches(monkeypatch, tmp_path):
    monkeypatch.delenv("WEAVE_CORTEX_DIR", raising=False)
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "a.md").write_text("# a\n", encoding="utf-8")
    cdir = cx.cortex_dir(Vault(tmp_path / "v"))
    assert "Library/Caches/theweave" in str(cdir)


def test_cortex_refuses_dir_inside_vault(vault, monkeypatch):
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(vault.root / "sneaky"))
    with pytest.raises(RuntimeError, match="I3"):
        cx.cortex_dir(vault)


def test_two_vaults_never_share_a_cortex(vault, tmp_path):
    other = tmp_path / "other-vault"
    other.mkdir()
    (other / "a.md").write_text("# a\n", encoding="utf-8")
    assert cx.cortex_dir(vault) != cx.cortex_dir(Vault(other))


# ---------------------------------------------------------------------------
# I1 — cache semantics: build -> delete -> rebuild -> byte-comparable manifest
# ---------------------------------------------------------------------------


def test_rebuild_delete_rebuild_manifest_byte_identical(vault):
    st1 = cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    assert st1.exists and st1.fresh
    m1 = (cx.cortex_dir(vault) / cx.MANIFEST_NAME).read_bytes()

    cx.clear(vault)
    assert not cx.cortex_exists(vault)

    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    m2 = (cx.cortex_dir(vault) / cx.MANIFEST_NAME).read_bytes()
    assert m1 == m2, "manifest must be byte-comparable across delete+rebuild"


def test_clear_loses_speed_never_memory(vault):
    """The vault is untouched by build+clear — memory lives in markdown only."""
    before = {n.rel_path: n.raw_text for n in vault.iter_notes()}
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    cx.clear(vault)
    after = {n.rel_path: n.raw_text for n in vault.iter_notes()}
    assert before == after


# ---------------------------------------------------------------------------
# I2 — derivation manifest + stale detection
# ---------------------------------------------------------------------------


def test_manifest_carries_derivation_fields(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    manifest = cx.read_manifest(cx.cortex_dir(vault))
    assert manifest["builder_version"] == cx.CORTEX_BUILDER_VERSION
    assert manifest["embed_model"] == cx.EMBED_MODEL
    assert manifest["sources"], "per-source content hashes required"
    dense = manifest["artifacts"]["dense.sqlite3"]
    assert dense["chunks"] > 0 and dense["model"] == "fake-sha"
    assert manifest["artifacts"]["graph.json"]["nodes"] > 0


def test_manifest_has_no_clock_fields(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    raw = (cx.cortex_dir(vault) / cx.MANIFEST_NAME).read_text(encoding="utf-8")
    low = raw.lower()
    for word in ("time", "date", "built_at", "created"):
        assert f'"{word}' not in low, f"clock-ish field {word!r} in manifest"


def test_edit_flags_stale(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    fresh, stale = cx.verify_fresh(vault)
    assert fresh and not stale

    target = vault.root / "entities" / "entity-Project-Orchard.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nEdited.\n",
                      encoding="utf-8")
    fresh, stale = cx.verify_fresh(vault)
    assert not fresh
    assert stale.get("entities/entity-Project-Orchard.md") == "changed"


def test_add_and_remove_flag_stale(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    (vault.root / "entities" / "entity-New.md").write_text(
        "---\ntype: project\n---\n# New\n", encoding="utf-8")
    _, stale = cx.verify_fresh(vault)
    assert stale.get("entities/entity-New.md") == "added"

    (vault.root / "entities" / "entity-New.md").unlink()
    (vault.root / "entities" / "entity-Petros.md").unlink()
    _, stale = cx.verify_fresh(vault)
    assert stale.get("entities/entity-Petros.md") == "removed"


def test_builder_version_mismatch_is_stale(vault, monkeypatch):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    monkeypatch.setattr(cx, "CORTEX_BUILDER_VERSION", "cortex-w99.0")
    fresh, stale = cx.verify_fresh(vault)
    assert not fresh and "<manifest>" in stale


# ---------------------------------------------------------------------------
# Incremental rebuild — unchanged files are never re-embedded
# ---------------------------------------------------------------------------


def test_incremental_rebuild_skips_unchanged(vault):
    emb1 = FakeEmbedder()
    cx.rebuild(vault, embedder=emb1, log=lambda *_: None)
    assert emb1.calls > 0

    emb2 = FakeEmbedder()
    cx.rebuild(vault, embedder=emb2, log=lambda *_: None)
    assert emb2.calls == 0, "unchanged vault must not re-embed anything"

    target = vault.root / "entities" / "entity-Marina.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nNew fact.\n",
                      encoding="utf-8")
    emb3 = FakeEmbedder()
    cx.rebuild(vault, embedder=emb3, log=lambda *_: None)
    assert 0 < emb3.calls <= 8, "only the edited file's chunks re-embed"


def test_dense_covers_sessions_excludes_archive(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    from weave.pro.dense import open_dense_db
    db = open_dense_db(cx.cortex_dir(vault))
    rels = [r[0] for r in db.execute("SELECT DISTINCT rel_path FROM chunks")]
    db.close()
    # Sessions are IN (W0 harness proved single-hop facts live there);
    # _archive stays out.
    assert any(r.startswith("sessions/") for r in rels)
    assert not any(r.startswith("_archive/") for r in rels)

    from weave.pro.graphrep import load_graph
    graph = load_graph(cx.cortex_dir(vault))
    assert any(k.startswith("session-") for k in graph["nodes"])
    assert graph["spectral"], "spectral embeddings present"


# ---------------------------------------------------------------------------
# Audit-wave regressions (2026-07-04 adversarial review)
# ---------------------------------------------------------------------------


def test_cortex_refuses_icloud_dir(vault, monkeypatch, tmp_path):
    fake_icloud = tmp_path / "Mobile Documents" / "com~apple~CloudDocs" / "cx"
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(fake_icloud))
    with pytest.raises(RuntimeError, match="I3"):
        cx.cortex_dir(vault)


def test_clear_preserves_bookkeeping_by_default(vault):
    from weave.pro.bookkeeping import log_retrieval, stats, BOOKKEEPING_DB
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    cdir = cx.cortex_dir(vault)
    log_retrieval(cdir, "recall", "q", ["entity-Marina"], session="t")
    cx.clear(vault)
    assert not cx.cortex_exists(vault), "derived artifacts gone"
    assert (cdir / BOOKKEEPING_DB).is_file(), "telemetry history survives"
    assert stats(cdir)["retrievals"] == 1
    cx.clear(vault, everything=True)
    assert not (cdir / BOOKKEEPING_DB).exists()
