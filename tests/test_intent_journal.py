"""Batch-apply intent journal (Item 3) — consolidator crash safety.

Contract under test:
  - apply() journals ONE pending intent (full patch set + pre/post hashes)
    BEFORE touching any file, and marks it completed after a fully
    successful loop (round trip: pending -> completed);
  - a simulated mid-batch death (killed between two files) leaves the record
    pending, and doctor flags it, listing patched vs unpatched targets;
  - a young pending record (apply in flight) is NOT flagged;
  - doctor reports — it never restores anything.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from weave.pro.consolidator import Consolidator
from weave.pro.intent_journal import (
    STATUS_COMPLETED, STATUS_PENDING, intents_dir, stale_pending,
)
from weave.vault import Vault, content_hash


SESSION_FOO = """---
date: '2026-08-15'
type: session
---

# Touched Foo

Worked on [[entity-Foo]].
"""

SESSION_BAR = """---
date: '2026-08-16'
type: session
---

# Touched Bar

Worked on [[entity-Bar]].
"""

ENTITY_BODY = """---
type: entity
status: current
valid_from: '2026-01-01'
valid_until: null
---

# {name}
"""


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    (root / "sessions").mkdir(parents=True)
    (root / "entities").mkdir()
    (root / "sessions" / "session-2026-08-15-foo.md").write_text(SESSION_FOO, encoding="utf-8")
    (root / "sessions" / "session-2026-08-16-bar.md").write_text(SESSION_BAR, encoding="utf-8")
    (root / "entities" / "entity-Foo.md").write_text(ENTITY_BODY.format(name="Foo"), encoding="utf-8")
    (root / "entities" / "entity-Bar.md").write_text(ENTITY_BODY.format(name="Bar"), encoding="utf-8")
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Vault(root)


def _apply(vault: Vault) -> list[str]:
    c = Consolidator(vault, window_days=30)
    report = c.build_report(today=date(2026, 8, 19))
    assert len(report.patches) == 2, "fixture must produce a 2-file batch"
    return c.apply(report)


def _intent_records(vault: Vault) -> list[tuple[Path, dict]]:
    d = intents_dir(vault)
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(d.glob("*.json"))]


# ---------- round trip: pending -> completed ----------

def test_successful_apply_round_trip(vault):
    patched = _apply(vault)
    assert sorted(patched) == ["entities/entity-Bar.md", "entities/entity-Foo.md"]

    records = _intent_records(vault)
    assert len(records) == 1
    _, record = records[0]
    assert record["status"] == STATUS_COMPLETED
    assert record["completed_at"] is not None
    assert len(record["targets"]) == 2

    # recorded hashes describe exactly the transition that happened
    for t in record["targets"]:
        current = content_hash(vault.read_text(t["rel_path"]))
        assert current == t["post_hash"]
        assert t["pre_hash"] != t["post_hash"]
        assert vault.exists(t["backup_rel_path"])
        assert content_hash(vault.read_text(t["backup_rel_path"])) == t["pre_hash"]

    # a completed record is never reported, at any age
    assert stale_pending(vault, stale_after_seconds=0) == []


def test_intent_written_before_any_patch(vault, monkeypatch):
    """The journal exists before the loop touches file #1 — a death at the
    very first backup still leaves a pending record behind."""
    import weave.pro.consolidator as consolidator

    def _die_immediately(src, dst):
        raise RuntimeError("simulated death before first file")

    monkeypatch.setattr(consolidator.shutil, "copy2", _die_immediately)
    with pytest.raises(RuntimeError):
        _apply(vault)
    records = _intent_records(vault)
    assert len(records) == 1
    assert records[0][1]["status"] == STATUS_PENDING


# ---------- mid-batch death ----------

@pytest.fixture
def dead_mid_batch(vault, monkeypatch):
    """Kill the apply loop between file 1 and file 2: file 1 fully patched,
    file 2 untouched, intent record left pending."""
    import weave.pro.consolidator as consolidator

    real_copy2 = consolidator.shutil.copy2
    calls = {"n": 0}

    def _copy2_then_die(src, dst):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("simulated mid-batch death")
        return real_copy2(src, dst)

    monkeypatch.setattr(consolidator.shutil, "copy2", _copy2_then_die)
    with pytest.raises(RuntimeError):
        _apply(vault)
    return vault


def test_mid_batch_death_leaves_pending_record(dead_mid_batch):
    records = _intent_records(dead_mid_batch)
    assert len(records) == 1
    assert records[0][1]["status"] == STATUS_PENDING


def test_stale_pending_lists_patched_vs_unpatched(dead_mid_batch):
    stale = stale_pending(dead_mid_batch, stale_after_seconds=0)
    assert len(stale) == 1
    rec = stale[0]
    states = {t.rel_path: t.state for t in rec.targets}
    assert sorted(states) == ["entities/entity-Bar.md", "entities/entity-Foo.md"]
    assert sorted(states.values()) == ["patched", "unpatched"]
    # the patched one carries its backup for a manual restore
    (patched_target,) = rec.patched()
    assert patched_target.backup_rel_path.startswith("_archive/")


def test_young_pending_record_is_not_flagged(dead_mid_batch):
    """An apply that started seconds ago is in flight, not a corpse."""
    assert stale_pending(dead_mid_batch) == []  # default threshold ~minutes


def test_doctor_flags_partial_batch_apply(dead_mid_batch):
    from weave.doctor import FAIL, check_vault

    # age the record past the staleness threshold
    (path, record) = _intent_records(dead_mid_batch)[0]
    record["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")

    g = check_vault(str(dead_mid_batch.root))
    checks = {c.name: c for c in g.checks}
    assert "batch-apply" in checks
    c = checks["batch-apply"]
    assert c.status == FAIL
    assert "Partial batch apply" in c.message
    # patched vs unpatched, named explicitly, plus the restore pointer
    assert "UNPATCHED:" in c.detail
    assert "patched:" in c.detail
    assert "_archive/" in c.detail
    assert "never auto-restores" in c.detail

    # doctor only REPORTED — nothing changed on disk
    assert _intent_records(dead_mid_batch)[0][1]["status"] == STATUS_PENDING


def test_mark_completed_failure_does_not_lose_the_apply(vault, monkeypatch):
    """A journal that turns unwritable AFTER a fully successful batch must
    not make apply() raise — caller keeps the return value, the report is
    still written, and doctor words the leftover as 'journal not finalized'
    (WARN), not 'Partial batch apply' (FAIL)."""
    import weave.pro.intent_journal as intent_journal
    from weave.doctor import WARN, check_vault

    def _boom(intent_path):
        raise OSError("simulated journal unwritable at finalize")

    monkeypatch.setattr(intent_journal, "mark_completed", _boom)
    patched = _apply(vault)  # must NOT raise
    assert sorted(patched) == ["entities/entity-Bar.md", "entities/entity-Foo.md"]
    # consolidation report still written
    assert list((vault.root / "_archive").glob("consolidation-*.md"))

    # record left pending, but every target shows its post-state
    (path, record) = _intent_records(vault)[0]
    assert record["status"] == STATUS_PENDING
    stale = stale_pending(vault, stale_after_seconds=0)
    assert len(stale) == 1 and stale[0].all_patched()

    # doctor: WARN with the finalization wording, not the partial-apply FAIL
    record["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")
    g = check_vault(str(vault.root))
    c = {c.name: c for c in g.checks}["batch-apply"]
    assert c.status == WARN
    assert "journal not finalized" in c.message
    assert "Partial batch apply" not in c.message
    assert "nothing to" in c.detail.lower() and "restore" in c.detail.lower()


def test_doctor_warns_when_journal_location_is_not_a_dir(vault):
    """A broken journal location must never read as a green safety net
    (stale_pending legitimately finds nothing in a non-directory)."""
    from weave.doctor import WARN, check_vault

    d = intents_dir(vault)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text("not a directory", encoding="utf-8")  # a file squats the intents path

    g = check_vault(str(vault.root))
    c = {c.name: c for c in g.checks}["batch-apply"]
    assert c.status == WARN
    assert "not a directory" in c.message


def test_doctor_passes_on_clean_vault(vault):
    from weave.doctor import PASS, check_vault

    _apply(vault)  # completed record present — not a failure
    g = check_vault(str(vault.root))
    checks = {c.name: c for c in g.checks}
    assert checks["batch-apply"].status == PASS
