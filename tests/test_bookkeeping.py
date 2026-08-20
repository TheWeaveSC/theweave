"""W3 bookkeeping — retrieval log, salience, co-occurrence, proposals.
The I5 test is the load-bearing one: a full bookkeeping+proposal cycle
mutates ZERO vault bytes."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro import bookkeeping as bk
from weave.pro.embedder import FakeEmbedder
from weave.pro.recall import recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "bench-vault"


@pytest.fixture
def built_vault(tmp_path, monkeypatch) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    v = Vault(vroot)
    cx.rebuild(v, embedder=FakeEmbedder(), log=lambda *_: None)
    return v


def _vault_bytes(v: Vault) -> dict[str, str]:
    return {n.rel_path: n.raw_text for n in v.iter_notes()}


def test_log_bumps_salience_and_cooccur(built_vault):
    cdir = cx.cortex_dir(built_vault)
    for _ in range(3):
        bk.log_retrieval(cdir, "recall", "lighthouse radio",
                         ["entity-Project-Lighthouse-v2", "entity-Vendor-Skyfield",
                          "session-2026-05-02-skyfield-order"], session="t")
    s = bk.stats(cdir)
    assert s["retrievals"] == 3 and s["notes_tracked"] == 3 and s["pairs"] == 3

    import sqlite3
    db = sqlite3.connect(cdir / bk.BOOKKEEPING_DB)
    count = db.execute("SELECT recall_count FROM salience WHERE note_name=?",
                       ("entity-Vendor-Skyfield",)).fetchone()[0]
    pair = db.execute("SELECT count FROM cooccur WHERE a=? AND b=?",
                      ("entity-Project-Lighthouse-v2", "entity-Vendor-Skyfield")).fetchone()[0]
    db.close()
    assert count == 3 and pair == 3


def test_recall_logs_into_cortex(built_vault):
    cdir = cx.cortex_dir(built_vault)
    before = bk.stats(cdir)["retrievals"]
    recall(built_vault, "orchard barcode bug", k=5, embedder=FakeEmbedder())
    assert bk.stats(cdir)["retrievals"] == before + 1


def test_proposal_cycle_zero_vault_writes(built_vault):
    """The I5 artifact test: log a week's worth of traffic, emit a proposal —
    the vault is byte-identical; the proposal exists in the CORTEX."""
    before = _vault_bytes(built_vault)
    cdir = cx.cortex_dir(built_vault)
    # unlinked pair recalled together often -> must surface as a proposal
    for _ in range(bk.COOCCUR_PROPOSE_MIN + 1):
        bk.log_retrieval(cdir, "recall", "harvest counts",
                         ["entity-Petros", "entity-Tool-Beacon"], session="t")
    out = bk.propose(built_vault, today=date(2026, 7, 4))

    assert _vault_bytes(built_vault) == before, "I5 violated: vault mutated"
    assert out.is_file()
    try:
        out.resolve().relative_to(built_vault.root)
        raise AssertionError("proposal landed inside the vault")
    except ValueError:
        pass
    text = out.read_text(encoding="utf-8")
    assert "PROPOSAL ONLY" in text
    assert "[[entity-Petros]]" in text and "[[entity-Tool-Beacon]]" in text


def test_linked_pairs_not_proposed(built_vault):
    cdir = cx.cortex_dir(built_vault)
    # Marina <-> Lighthouse-v2 are already wikilinked in the fixture
    for _ in range(bk.COOCCUR_PROPOSE_MIN + 2):
        bk.log_retrieval(cdir, "recall", "marina lighthouse",
                         ["entity-Marina", "entity-Project-Lighthouse-v2"], session="t")
    text = bk.propose(built_vault, today=date(2026, 7, 4)).read_text(encoding="utf-8")
    assert "`[[entity-Marina]]` ↔ `[[entity-Project-Lighthouse-v2]]`" not in text


def test_staleness_flags_high_salience_old_notes(built_vault):
    cdir = cx.cortex_dir(built_vault)
    # entity-Team-Cobalt: valid_from 2025-06-01, current -> stale by 2026-07-04
    for _ in range(5):
        bk.log_retrieval(cdir, "recall", "cobalt retro", ["entity-Team-Cobalt"],
                         session="t")
    text = bk.propose(built_vault, today=date(2026, 7, 4)).read_text(encoding="utf-8")
    assert "entity-Team-Cobalt" in text.split("## Staleness flags")[1].split("##")[0]


def test_logging_failure_never_breaks_recall(built_vault, monkeypatch):
    import weave.pro.bookkeeping as bkmod
    def boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(bkmod, "log_retrieval", boom)
    r = recall(built_vault, "lighthouse", k=3, embedder=FakeEmbedder())
    assert r.hits, "telemetry failure must not break the read path"


def test_query_text_never_persisted(built_vault):
    """I4: the log keeps a hash, never the verbatim query (session dialogue)."""
    import sqlite3
    cdir = cx.cortex_dir(built_vault)
    secret = "what did the chair decide about the confidential merger"
    bk.log_retrieval(cdir, "recall", secret, ["entity-Marina"], session="t")
    raw = (cdir / bk.BOOKKEEPING_DB).read_bytes()
    assert b"confidential merger" not in raw
    db = sqlite3.connect(cdir / bk.BOOKKEEPING_DB)
    q = db.execute("SELECT query FROM retrieval_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    db.close()
    assert len(q) == 12 and all(c in "0123456789abcdef" for c in q)
