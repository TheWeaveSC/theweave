"""L5 advisory cross-machine lease tests.

Covers the ARCH-AUDIT finding: L0's in-process CAS does not close a
cross-machine race, and LD#17's one-writer-per-project discipline is pure
prose. These tests exercise weave/lease.py directly and through the
WeaveCore verb layer (core.py), all against temp dirs — no iCloud needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weave.core import WeaveCore
from weave.lease import (
    ConflictCopyError,
    LeaseHandle,
    LeaseHeldError,
    acquire,
    find_conflict_copies,
    heartbeat,
    release,
)
from weave.vault import Vault


def _vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path)


def _core(tmp_path: Path) -> WeaveCore:
    return WeaveCore(_vault(tmp_path))


def _sidecar_path(tmp_path: Path, rel: str) -> Path:
    p = tmp_path / rel
    return p.parent / f".{p.name}.weavelock"


def _write_raw_sidecar(tmp_path: Path, rel: str, **overrides) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    data = {
        "owner": "other-owner",
        "host": "other-host",
        "pid": 9999,
        "acquired_at": now,
        "heartbeat": now,
        "nonce": "deadbeef",
    }
    data.update(overrides)
    sc = _sidecar_path(tmp_path, rel)
    sc.parent.mkdir(parents=True, exist_ok=True)
    sc.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# ---------- acquire / release roundtrip ----------

def test_acquire_then_release_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    handle = acquire(v, "note.md")
    sc = _sidecar_path(tmp_path, "note.md")
    assert sc.exists()
    data = json.loads(sc.read_text())
    assert data["nonce"] == handle.nonce
    assert "owner" in data and "host" in data and "pid" in data
    assert "heartbeat" in data and "acquired_at" in data

    release(v, handle)
    assert not sc.exists()
    # Target untouched by lease acquire/release.
    assert (tmp_path / "note.md").read_text() == "hello"


# ---------- competing live lease ----------

def test_competing_live_lease_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    core = _core(tmp_path)
    core.create("note.md", "v1")

    _write_raw_sidecar(tmp_path, "note.md", owner="SC-Mini", host="Mini.local", pid=1234)

    with pytest.raises(LeaseHeldError) as exc_info:
        core.str_replace("note.md", "v1", "v2")

    msg = str(exc_info.value)
    assert "SC-Mini" in msg
    assert "Mini.local" in msg
    assert exc_info.value.owner == "SC-Mini"
    assert exc_info.value.host == "Mini.local"

    # Target bytes unchanged — the write never happened.
    assert (tmp_path / "note.md").read_text() == "v1"


# ---------- stale lease takeover ----------

def test_stale_lease_takeover(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WEAVE_LEASE_TTL_S", "1")
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    _write_raw_sidecar(tmp_path, "note.md", heartbeat=old, acquired_at=old, nonce="stale-nonce")

    handle = acquire(v, "note.md")
    assert handle.nonce != "stale-nonce"

    sc = _sidecar_path(tmp_path, "note.md")
    data = json.loads(sc.read_text())
    assert data["nonce"] == handle.nonce


def test_stale_lease_takeover_via_core_write(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: a str_replace succeeds after the prior lease goes stale."""
    monkeypatch.setenv("WEAVE_LEASE_TTL_S", "1")
    core = _core(tmp_path)
    core.create("note.md", "v1")

    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    _write_raw_sidecar(tmp_path, "note.md", heartbeat=old, acquired_at=old)

    msg = core.str_replace("note.md", "v1", "v2")
    assert msg == "replaced 1 occurrence in note.md"
    assert (tmp_path / "note.md").read_text() == "v2"


# ---------- heartbeat refresh ----------

def test_heartbeat_refresh(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    handle = acquire(v, "note.md")

    sc = _sidecar_path(tmp_path, "note.md")
    before = json.loads(sc.read_text())["heartbeat"]

    # Backdate on disk so the refresh is observably different, then heartbeat.
    data = json.loads(sc.read_text())
    data["heartbeat"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    sc.write_text(json.dumps(data, indent=2), encoding="utf-8")
    backdated = data["heartbeat"]

    heartbeat(v, handle)
    after = json.loads(sc.read_text())["heartbeat"]
    after_nonce = json.loads(sc.read_text())["nonce"]

    assert after != backdated
    assert after_nonce == handle.nonce
    assert before != backdated  # sanity: we actually changed it before refresh


# ---------- release only if our nonce ----------

def test_release_only_if_our_nonce(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    handle_a = acquire(v, "note.md")

    # Simulate a takeover: someone else's nonce now sits in the sidecar.
    sc = _sidecar_path(tmp_path, "note.md")
    other = {
        "owner": "someone-else",
        "host": "other-host",
        "pid": 555,
        "acquired_at": "2026-01-01T00:00:00.000Z",
        "heartbeat": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "nonce": "nonce-b",
    }
    sc.write_text(json.dumps(other, indent=2), encoding="utf-8")

    release(v, handle_a)

    assert sc.exists()
    assert json.loads(sc.read_text())["nonce"] == "nonce-b"


# ---------- conflict-copy detection ----------

def test_conflict_copy_detected_by_find_conflict_copies(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    (tmp_path / "note 2.md").write_text("conflict copy", encoding="utf-8")

    copies = find_conflict_copies(v, "note.md")
    assert copies == ["note 2.md"]


def test_conflict_copy_detected_via_core_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    core = _core(tmp_path)
    core.create("note.md", "v1")
    (tmp_path / "note 2.md").write_text("conflict copy", encoding="utf-8")

    with pytest.raises(ConflictCopyError) as exc_info:
        core.str_replace("note.md", "v1", "v2")
    assert "note 2.md" in str(exc_info.value)

    # No write occurred.
    assert (tmp_path / "note.md").read_text() == "v1"
    # No lease sidecar left behind either (guard fires before acquire).
    assert not _sidecar_path(tmp_path, "note.md").exists()


def test_conflict_copy_legit_name_not_flagged(tmp_path: Path) -> None:
    """A different note's own name should not spuriously match."""
    v = _vault(tmp_path)
    v.write_text("weekly-2026.md", "hi")
    (tmp_path / "unrelated.md").write_text("x", encoding="utf-8")
    assert find_conflict_copies(v, "weekly-2026.md") == []


# ---------- conflict-copy override escape hatch ----------

def test_conflict_copy_false_positive_blocks_write_by_default(tmp_path: Path, monkeypatch) -> None:
    """A legitimately-named file that happens to match the '<stem> N.md'
    heuristic (e.g. someone genuinely named a file 'weekly-2026 3.md')
    permanently blocks writes to 'weekly-2026.md' with no override set.
    This documents the heuristic's false-positive cost that the override
    below exists to escape."""
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    monkeypatch.delenv("WEAVE_ALLOW_CONFLICT_COPIES", raising=False)
    core = _core(tmp_path)
    core.create("weekly-2026.md", "v1")
    # Legitimately-named sibling, not an actual iCloud conflict copy.
    (tmp_path / "weekly-2026 3.md").write_text("a real, separate note", encoding="utf-8")

    with pytest.raises(ConflictCopyError):
        core.str_replace("weekly-2026.md", "v1", "v2")


def test_conflict_copy_override_env_lets_write_proceed(tmp_path: Path, monkeypatch) -> None:
    """WEAVE_ALLOW_CONFLICT_COPIES=1 downgrades the guard to a no-op so a
    heuristic false-positive can never permanently brick writes to a path
    — the user has an escape hatch."""
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    monkeypatch.setenv("WEAVE_ALLOW_CONFLICT_COPIES", "1")
    core = _core(tmp_path)
    core.create("weekly-2026.md", "v1")
    (tmp_path / "weekly-2026 3.md").write_text("a real, separate note", encoding="utf-8")

    msg = core.str_replace("weekly-2026.md", "v1", "v2")
    assert msg == "replaced 1 occurrence in weekly-2026.md"
    assert (tmp_path / "weekly-2026.md").read_text() == "v2"
    # The unrelated sibling file is untouched.
    assert (tmp_path / "weekly-2026 3.md").read_text() == "a real, separate note"


@pytest.mark.parametrize("allow_value", ["1", "true", "True", "yes", "on"])
def test_conflict_copy_override_env_accepted_values(
    tmp_path: Path, monkeypatch, allow_value: str
) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    monkeypatch.setenv("WEAVE_ALLOW_CONFLICT_COPIES", allow_value)
    core = _core(tmp_path)
    core.create("note.md", "v1")
    (tmp_path / "note 2.md").write_text("conflict copy", encoding="utf-8")

    msg = core.str_replace("note.md", "v1", "v2")
    assert msg == "replaced 1 occurrence in note.md"


# ---------- single-writer path unaffected ----------

def test_single_writer_unaffected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    core = _core(tmp_path)

    msg1 = core.create("note.md", "v1")
    assert msg1 == "created: note.md (2 chars)"

    msg2 = core.str_replace("note.md", "v1", "v2")
    assert msg2 == "replaced 1 occurrence in note.md"

    msg3 = core.insert("note.md", 0, "top line")
    assert msg3 == "inserted at line 0 in note.md"

    msg4 = core.delete("note.md")
    assert msg4 == "deleted: note.md"

    # No lease sidecar left behind after any verb (acquire+release balanced).
    assert not _sidecar_path(tmp_path, "note.md").exists()


# ---------- off switch ----------

@pytest.mark.parametrize("off_value", ["0", "false", "False", "no", "off"])
def test_off_switch_noop(tmp_path: Path, monkeypatch, off_value: str) -> None:
    monkeypatch.setenv("WEAVE_LEASE", off_value)
    core = _core(tmp_path)
    core.create("note.md", "v1")

    # A live competing lease exists...
    _write_raw_sidecar(tmp_path, "note.md", owner="SC-Mini", host="Mini.local", pid=1234)

    # ...but with the off-switch set, it's ignored entirely.
    msg = core.str_replace("note.md", "v1", "v2")
    assert msg == "replaced 1 occurrence in note.md"
    assert (tmp_path / "note.md").read_text() == "v2"

    # We did not create/overwrite our own sidecar either — the pre-existing
    # (ignored) one is left exactly as it was.
    sc = _sidecar_path(tmp_path, "note.md")
    assert json.loads(sc.read_text())["owner"] == "SC-Mini"


def test_off_switch_conflict_copy_also_bypassed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WEAVE_LEASE", "0")
    core = _core(tmp_path)
    core.create("note.md", "v1")
    (tmp_path / "note 2.md").write_text("conflict copy", encoding="utf-8")

    # Off-switch bypasses the conflict-copy guard too.
    msg = core.str_replace("note.md", "v1", "v2")
    assert msg == "replaced 1 occurrence in note.md"


# ---------- lease sidecar invisibility ----------

def test_lease_sidecar_invisible_to_iter_notes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    handle = acquire(v, "note.md")
    try:
        names = [n.rel_path for n in v.iter_notes()]
        assert ".note.md.weavelock" not in names
        assert "note.md" in names
    finally:
        release(v, handle)


def test_lease_sidecar_invisible_to_doctor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    from weave.doctor import check_vault

    v = _vault(tmp_path)
    v.write_text("note.md", "hello")
    handle = acquire(v, "note.md")
    try:
        group = check_vault(str(tmp_path))
        # Doctor's iCloud conflict-copy check should not treat the lease
        # sidecar itself as a conflict copy or otherwise choke on it.
        for check in group.checks:
            assert ".weavelock" not in (check.detail or "")
        conflict_check = next(c for c in group.checks if c.name == "icloud-conflicts")
        assert conflict_check.status == "pass"
    finally:
        release(v, handle)


# ---------- torn lease impossible ----------

def test_torn_lease_impossible_on_exclusive_create_failure(tmp_path: Path, monkeypatch) -> None:
    """Fresh acquire() uses the O_EXCL fast path (no prior sidecar). If the
    write after the exclusive create fails partway (e.g. fsync errors), the
    sidecar must not be left behind half-written — acquire() cleans up the
    file it just created rather than leaving a torn/partial lease."""
    import os as _os

    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    real_fsync = _os.fsync

    def boom(fd):
        raise OSError("simulated crash during fsync")

    monkeypatch.setattr(_os, "fsync", boom)
    with pytest.raises(OSError):
        acquire(v, "note.md")
    monkeypatch.setattr(_os, "fsync", real_fsync)

    sc = _sidecar_path(tmp_path, "note.md")
    assert not sc.exists()
    # No leftover tempfiles for the sidecar (the exclusive-create path
    # writes the sidecar directly, not via a tempfile+replace).
    leftovers = list(tmp_path.glob(f".{sc.name}.*.tmp"))
    assert leftovers == []
    # Target file untouched.
    assert (tmp_path / "note.md").read_text() == "hello"


def test_torn_lease_impossible_on_takeover_replace_failure(tmp_path: Path, monkeypatch) -> None:
    """Takeover of an already-existing stale lease still goes through
    _atomic_write (tempfile + os.replace). If os.replace fails partway,
    no torn sidecar and no leftover tempfile is left behind."""
    import os as _os

    monkeypatch.setenv("WEAVE_LEASE_TTL_S", "1")
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    _write_raw_sidecar(tmp_path, "note.md", heartbeat=old, acquired_at=old, nonce="stale-nonce")

    real_replace = _os.replace

    def boom(src, dst):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError):
        acquire(v, "note.md")
    monkeypatch.setattr(_os, "replace", real_replace)

    sc = _sidecar_path(tmp_path, "note.md")
    # The original stale sidecar is left exactly as it was (takeover failed).
    assert sc.exists()
    assert json.loads(sc.read_text())["nonce"] == "stale-nonce"
    # No leftover tempfiles for the sidecar.
    leftovers = list(tmp_path.glob(f".{sc.name}.*.tmp"))
    assert leftovers == []
    # Target file untouched.
    assert (tmp_path / "note.md").read_text() == "hello"


# ---------- same-machine race: O_EXCL closes it for real ----------

def test_same_machine_race_exactly_one_acquire_succeeds(tmp_path: Path, monkeypatch) -> None:
    """Sequential sanity check: two acquire() calls on the same path with
    no release in between: exactly one succeeds, the second raises
    LeaseHeldError."""
    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    handle1 = acquire(v, "note.md")

    with pytest.raises(LeaseHeldError) as exc_info:
        acquire(v, "note.md")

    assert exc_info.value.owner == handle1.owner
    assert exc_info.value.host == handle1.host
    assert exc_info.value.pid == handle1.pid

    sc = _sidecar_path(tmp_path, "note.md")
    assert json.loads(sc.read_text())["nonce"] == handle1.nonce


def test_same_machine_race_true_concurrency_exactly_one_wins(
    tmp_path: Path, monkeypatch
) -> None:
    """Genuine concurrent race, not just two sequential calls: N threads on
    the same process call acquire() on the same path at (as close to)
    the same instant as a barrier can arrange, with no prior sidecar.

    This is the must_fix regression test — it FAILS if the O_EXCL
    exclusive create is removed and acquire() goes back to plain
    read-check-then-write, because without an OS-enforced exclusive
    create, multiple threads can each read "absent" before any of them
    writes, and more than one would then "succeed" (last write wins,
    silently), instead of exactly one succeeding and the rest correctly
    losing with LeaseHeldError."""
    import threading

    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    n = 8
    barrier = threading.Barrier(n)
    results: list[object] = [None] * n

    def worker(i: int) -> None:
        barrier.wait()  # release all threads as close to simultaneously as possible
        try:
            results[i] = acquire(v, "note.md")
        except LeaseHeldError as e:
            results[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if isinstance(r, LeaseHandle)]
    refusals = [r for r in results if isinstance(r, LeaseHeldError)]

    assert len(successes) == 1, (
        f"expected exactly 1 acquire() to succeed under concurrent racing, "
        f"got {len(successes)} (O_EXCL exclusivity broken)"
    )
    assert len(refusals) == n - 1

    sc = _sidecar_path(tmp_path, "note.md")
    assert json.loads(sc.read_text())["nonce"] == successes[0].nonce


def test_same_machine_race_o_excl_used_for_fresh_acquire(tmp_path: Path, monkeypatch) -> None:
    """Directly verify the fresh-acquire path opens the sidecar with
    O_EXCL: a real filesystem-level create-once-only flag, not a Python-
    level read-check that leaves a TOCTOU gap open to a racing process."""
    import os as _os

    monkeypatch.delenv("WEAVE_LEASE", raising=False)
    v = _vault(tmp_path)
    v.write_text("note.md", "hello")

    seen_flags = []
    real_open = _os.open

    def spy_open(path, flags, *a, **kw):
        seen_flags.append(flags)
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(_os, "open", spy_open)
    acquire(v, "note.md")
    monkeypatch.setattr(_os, "open", real_open)

    assert seen_flags, "expected acquire() to call os.open for the sidecar"
    assert all(f & _os.O_EXCL for f in seen_flags)
    assert all(f & _os.O_CREAT for f in seen_flags)


# ---------- regression: full suite stays green is verified by CI/run command,
# not re-asserted here to avoid nested pytest invocation. ----------
