"""W4 dreamer — the one sanctioned vault write; scratch provably deleted;
LLM failure is loud (no fabricated brief)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro.embedder import FakeEmbedder
from weave.pro.dreamer import dream, gather, DreamError, launchd_plist

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "bench-vault"
DAY = date(2026, 7, 1)  # signals-2026-06 (valid_from 2026-06-30) in window


@pytest.fixture
def built_vault(tmp_path, monkeypatch) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    v = Vault(vroot)
    cx.rebuild(v, embedder=FakeEmbedder(), log=lambda *_: None)
    return v


def mock_llm(prompt: str) -> str:
    assert "signals" in prompt.lower()
    return "- Watch buoy 4 battery telemetry before winter.\n- Barcode fix owner named at retro."


def test_dream_writes_brief_via_write_path_only(built_vault):
    before = {n.rel_path: n.raw_text for n in built_vault.iter_notes()}
    res = dream(built_vault, day=DAY, llm=mock_llm)
    after = {n.rel_path: n.raw_text for n in built_vault.iter_notes()}

    new_paths = set(after) - set(before)
    assert new_paths == {res.brief_rel_path}, "exactly ONE new vault file: the brief"
    assert all(after[p] == before[p] for p in before), "no existing note touched"

    text = after[res.brief_rel_path]
    assert "type: morning-brief" in text
    assert "buoy 4 battery" in text
    assert res.signals_used >= 1


def test_scratch_deleted_after_brief(built_vault):
    res = dream(built_vault, day=DAY, llm=mock_llm)
    assert res.scratch_deleted
    scratch_dir = cx.cortex_dir(built_vault) / "scratch"
    assert not any(scratch_dir.iterdir()), "scratch must not survive the night"


def test_scratch_deleted_even_on_llm_failure(built_vault):
    def dead_llm(prompt: str) -> str:
        raise DreamError("ollama down")
    with pytest.raises(DreamError):
        dream(built_vault, day=DAY, llm=dead_llm)
    scratch_dir = cx.cortex_dir(built_vault) / "scratch"
    assert not any(scratch_dir.iterdir())
    # and no brief was fabricated
    assert not any(n.rel_path.startswith("briefs/") for n in built_vault.iter_notes())


def test_dry_run_writes_nothing(built_vault):
    before = {n.rel_path for n in built_vault.iter_notes()}
    dream(built_vault, day=DAY, llm=mock_llm, dry_run=True)
    assert {n.rel_path for n in built_vault.iter_notes()} == before


def test_gather_windows_signals(built_vault):
    m = gather(built_vault, DAY)
    names = [n.name for n in m["signals"]]
    assert "signals-2026-06" in names          # 2026-06-30 within 3d of 07-01
    assert "signals-2026-04" not in names      # far outside the window


def test_launchd_plist_shape():
    p = launchd_plist("/tmp/v", "/usr/bin/python3", 3, 30, "/tmp/log")
    assert "com.theweave.cortex.nightly" in p
    assert "<integer>3</integer>" in p and "<integer>30</integer>" in p
    assert "WEAVE_VAULT_PATH" in p and "/tmp/v" in p


def test_gather_includes_future_dated_monthly_file(built_vault):
    """Monthly signal files carry month-END valid_from; the window is a lower
    bound only (audit fix: an upper bound hid the current month's file)."""
    m = gather(built_vault, date(2026, 6, 28))  # 2 days BEFORE valid_from
    assert "signals-2026-06" in [n.name for n in m["signals"]]


def test_echoed_evidence_bullets_rejected(built_vault):
    """A model quoting the prompt's own evidence bullets back must not pass
    the contract as fabricated anticipations."""
    from weave.pro.dreamer import DreamError
    def echo_llm(prompt: str) -> str:
        lines = [ln for ln in prompt.splitlines() if ln.startswith("- ")]
        return "\n".join(lines[:4]) if lines else "- something original"
    with pytest.raises(DreamError):
        dream(built_vault, day=DAY, llm=echo_llm)


def test_plist_survives_xml_metachars():
    import plistlib
    p = launchd_plist("/tmp/R&D vaults/Mini", "/usr/bin/python3", 3, 30, "/tmp/log")
    parsed = plistlib.loads(p.encode())
    assert parsed["EnvironmentVariables"]["WEAVE_VAULT_PATH"] == "/tmp/R&D vaults/Mini"
