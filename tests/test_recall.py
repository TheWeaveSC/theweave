"""Hybrid recall (W2) — offline mechanics + I6 degradation. FakeEmbedder has
no semantics, so these tests pin BEHAVIOR (degrade, include-superseded,
determinism, staleness flag); retrieval QUALITY is measured by the real-model
A/B recorded in docs/CORTEX-RESULTS.md."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro.embedder import FakeEmbedder
from weave.pro.recall import recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "bench-vault"


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


# ---------------------------------------------------------------------------
# I6 — degrade loudly, never fail a read
# ---------------------------------------------------------------------------


def test_no_cortex_degrades_to_ppr(vault):
    r = recall(vault, "lighthouse buoy firmware", k=5, embedder=FakeEmbedder())
    assert r.degraded
    assert "rebuild" in r.note
    assert r.hits, "degraded mode still answers via PPR"
    assert "DEGRADED" in r.to_text()


def test_embedder_down_degrades_to_ppr(built_vault):
    class DeadEmbedder:
        name = "dead"
        def embed(self, texts):
            raise RuntimeError("connection refused")
    r = recall(built_vault, "lighthouse buoy firmware", k=5, embedder=DeadEmbedder())
    assert r.degraded and "embedder unavailable" in r.note
    assert r.hits


def test_recall_never_writes_vault(built_vault):
    before = {n.rel_path: n.raw_text for n in built_vault.iter_notes()}
    recall(built_vault, "orchard barcode", k=5, embedder=FakeEmbedder())
    after = {n.rel_path: n.raw_text for n in built_vault.iter_notes()}
    assert before == after


# ---------------------------------------------------------------------------
# Mechanics with a built cortex
# ---------------------------------------------------------------------------


def test_recall_returns_ranked_hits(built_vault):
    r = recall(built_vault, "Lighthouse radio fault at the pier", k=6,
               embedder=FakeEmbedder())
    assert not r.degraded
    assert len(r.hits) <= 6 and r.hits
    scores = [h.score for h in r.hits]
    assert scores == sorted(scores, reverse=True)
    # entity-name seeding fires even with a semantics-free embedder
    assert any("lighthouse" in s.lower() for s in r.seeds)


def test_superseded_notes_reachable_and_marked(built_vault):
    r = recall(built_vault, "Lighthouse project history", k=24,
               embedder=FakeEmbedder())
    marked = {h.note_name: h.superseded for h in r.hits}
    assert marked.get("entity-Project-Lighthouse") is True, \
        "superseded v1 must be reachable through recall (unlike boot)"
    assert marked.get("entity-Project-Lighthouse-v2") is False


def test_recall_deterministic(built_vault):
    a = recall(built_vault, "skyfield lora module order", k=8, embedder=FakeEmbedder())
    b = recall(built_vault, "skyfield lora module order", k=8, embedder=FakeEmbedder())
    assert [h.note_name for h in a.hits] == [h.note_name for h in b.hits]
    assert a.to_text() == b.to_text()


def test_stale_cortex_flagged_but_answers(built_vault):
    target = built_vault.root / "entities" / "entity-Marina.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nEdit.\n",
                      encoding="utf-8")
    r = recall(built_vault, "marina harbor master", k=5, embedder=FakeEmbedder())
    assert not r.degraded
    assert r.stale, "I2: stale sources must be surfaced on read"
    assert "STALE" in r.to_text()


def test_abstention_floor(built_vault):
    # FakeEmbedder vectors are ~orthogonal: max dense sim ~0 -> abstain fires.
    r = recall(built_vault, "what is the capital of Mars", k=5,
               embedder=FakeEmbedder())
    assert r.abstained
    assert "ABSTAINED" in r.to_text()


# ---------------------------------------------------------------------------
# MCP wiring — recall registered on rw AND readonly instances
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("readonly", ["0", "1"])
def test_mcp_recall_registered(vault, monkeypatch, readonly):
    import asyncio
    monkeypatch.setenv("WEAVE_VAULT_PATH", str(vault.root))
    monkeypatch.setenv("WEAVE_READONLY", readonly)
    from weave.mcp_server import build_server
    tools = asyncio.get_event_loop().run_until_complete(build_server().list_tools())
    names = {t.name for t in tools}
    assert "recall" in names and "view" in names and "hydrate" in names
    if readonly == "1":
        assert "create" not in names


# ---------------------------------------------------------------------------
# Audit-wave regressions (2026-07-04 adversarial review)
# ---------------------------------------------------------------------------


def test_missing_dense_index_degrades_not_fabricates(built_vault):
    """A partial cortex (manifest present, dense.sqlite3 gone) must degrade
    loudly — not create an empty index and abstain on everything."""
    from weave.pro.dense import DENSE_DB
    db_path = cx.cortex_dir(built_vault) / DENSE_DB
    db_path.unlink()
    r = recall(built_vault, "lighthouse radio fault", k=5, embedder=FakeEmbedder())
    assert r.degraded and "dense index unavailable" in r.note
    assert r.hits, "degraded mode still answers via PPR"
    assert not db_path.exists(), "a READ must never create an index file"


def test_boot_path_excludes_superseded(built_vault):
    r = recall(built_vault, "Lighthouse project history", k=24,
               embedder=FakeEmbedder(), include_superseded=False)
    names = [h.note_name for h in r.hits]
    assert "entity-Project-Lighthouse" not in names
    assert "entity-Project-Lighthouse-v2" in names


def test_readonly_peer_never_logs(built_vault, monkeypatch):
    from weave.pro.bookkeeping import stats
    cdir = cx.cortex_dir(built_vault)
    monkeypatch.setenv("WEAVE_READONLY", "1")
    before = stats(cdir)["retrievals"]
    recall(built_vault, "orchard barcode", k=3, embedder=FakeEmbedder())
    assert stats(cdir)["retrievals"] == before
