"""Write-path hardening tests: atomic writes, safe delete, path-leak scrubbing.

Covers the ARCH-AUDIT findings fixed in weave/L0-write-path-hardening:
  1. Atomic write (no torn files on crash-mid-write).
  2. Safe delete (tombstone into .trash/, never a hard unlink).
  3. No absolute host paths leaked in error messages.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from weave.vault import Vault, VaultConflictError, VaultPathError


def _vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path)


# ---------- atomic write ----------

def test_write_text_creates_file_with_content(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "hello world")
    assert (tmp_path / "note.md").read_text() == "hello world"


def test_write_text_overwrites_existing(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "v1")
    v.write_text("note.md", "v2")
    assert (tmp_path / "note.md").read_text() == "v2"


def test_atomic_write_crash_after_tempfile_leaves_old_content(tmp_path: Path, monkeypatch) -> None:
    """Simulate a crash between tempfile-fsync and os.replace: destination
    must still hold the OLD content, and no leftover tempfile remains."""
    v = _vault(tmp_path)
    v.write_text("note.md", "original content")

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        v.write_text("note.md", "new content that should never land")
    monkeypatch.setattr(os, "replace", real_replace)

    # Destination unchanged.
    assert (tmp_path / "note.md").read_text() == "original content"
    # No leftover tempfiles.
    leftovers = list(tmp_path.glob(".note.md.*.tmp"))
    assert leftovers == [], f"tempfile(s) not cleaned up after crash: {leftovers}"


def test_atomic_write_tempfile_same_directory_as_destination(tmp_path: Path, monkeypatch) -> None:
    """mkstemp must be called with dir=destination's parent — required for
    os.replace to be atomic (same filesystem)."""
    v = _vault(tmp_path)
    (tmp_path / "sub").mkdir()

    seen_dirs = []
    import tempfile as tempfile_mod
    real_mkstemp = tempfile_mod.mkstemp

    def spy_mkstemp(*args, **kwargs):
        seen_dirs.append(kwargs.get("dir"))
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile_mod, "mkstemp", spy_mkstemp)
    v.write_text("sub/note.md", "content")

    assert len(seen_dirs) == 1
    assert Path(seen_dirs[0]) == tmp_path / "sub"


def test_atomic_write_no_torn_file_under_concurrent_reader(tmp_path: Path) -> None:
    """A reader thread continuously re-reads the file while a writer thread
    hammers it with same-directory overwrites of two very different-length,
    single-character-repeated payloads. Every single read the reader
    observes must be entirely 'A's or entirely 'B's of the exact expected
    length — never a truncated or mixed-content read.

    This is a real regression test, not just a sanity check: it FAILS
    reliably under a naive non-atomic implementation (e.g. `open(p, "w")`
    truncate-then-write in place), because a concurrent read can land
    between the truncate and the write and observe a partial/empty/mixed
    file. A prior version of this test only wrote sequentially in a single
    thread with no concurrent reader or crash injection, so it passed even
    against that naive implementation — asserting nothing about atomicity.
    os.replace()-based atomic write (the real implementation) always
    passes this because the destination inode is swapped in one syscall;
    a concurrent open() either sees the whole old file or the whole new
    file, never a torn mix.
    """
    import threading

    v = _vault(tmp_path)
    target = tmp_path / "note.md"
    payload_a = "A" * 200_000
    payload_b = "B" * 3  # deliberately a very different length from A
    v.write_text("note.md", payload_a)

    stop = threading.Event()
    violations: list[str] = []
    iterations = 300

    def writer() -> None:
        for i in range(iterations):
            v.write_text("note.md", payload_a if i % 2 == 0 else payload_b)
        stop.set()

    def reader() -> None:
        while not stop.is_set():
            try:
                data = target.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                # A missing/unreadable file mid-swap would itself be a
                # torn-write symptom under a truncate-based implementation.
                violations.append("read failed: file missing or unreadable mid-write")
                continue
            if data not in (payload_a, payload_b):
                violations.append(f"torn read: len={len(data)!r} content={data[:20]!r}...")
                if len(violations) > 20:
                    return

    t_writer = threading.Thread(target=writer)
    t_reader = threading.Thread(target=reader)
    t_reader.start()
    t_writer.start()
    t_writer.join(timeout=30)
    stop.set()
    t_reader.join(timeout=30)

    assert violations == [], (
        f"observed {len(violations)} torn/invalid read(s) during concurrent "
        f"writes, e.g.: {violations[:5]}"
    )


# ---------- CAS / optimistic concurrency ----------

def test_write_text_if_unchanged_succeeds_when_no_conflict(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "v1")
    text, h = v.read_text_with_hash("note.md")
    v.write_text_if_unchanged("note.md", "v2", h)
    assert (tmp_path / "note.md").read_text() == "v2"


def test_write_text_if_unchanged_raises_on_concurrent_modification(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "v1")
    text, h = v.read_text_with_hash("note.md")

    # Writer B modifies the file after A's read.
    v.write_text("note.md", "writer-B-content")

    with pytest.raises(VaultConflictError):
        v.write_text_if_unchanged("note.md", "writer-A-content", h)

    # Writer B's bytes must survive untouched.
    assert (tmp_path / "note.md").read_text() == "writer-B-content"


def test_write_text_if_unchanged_survives_mtime_churn(tmp_path: Path) -> None:
    """iCloud rewrites mtimes without changing bytes; CAS must key off
    content hash, not mtime, so this must NOT raise."""
    v = _vault(tmp_path)
    v.write_text("note.md", "v1")
    text, h = v.read_text_with_hash("note.md")

    # Touch the file: change mtime only, not content.
    p = tmp_path / "note.md"
    os.utime(p, (p.stat().st_atime + 1000, p.stat().st_mtime + 1000))

    # Must succeed since content hash still matches.
    v.write_text_if_unchanged("note.md", "v2", h)
    assert p.read_text() == "v2"


def test_read_text_with_hash_matches_manual_sha256(tmp_path: Path) -> None:
    import hashlib
    v = _vault(tmp_path)
    v.write_text("note.md", "some content")
    text, h = v.read_text_with_hash("note.md")
    assert text == "some content"
    assert h == hashlib.sha256(b"some content").hexdigest()


# ---------- safe delete / tombstone ----------

def test_delete_moves_file_to_trash_not_hard_unlink(tmp_path: Path, monkeypatch) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "delete me")

    unlink_calls = []
    real_unlink = Path.unlink

    def spy_unlink(self, *a, **kw):
        unlink_calls.append(self)
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", spy_unlink)
    v.delete("note.md")

    assert unlink_calls == [], f"Path.unlink was called for a file delete: {unlink_calls}"
    assert not (tmp_path / "note.md").exists()


def test_delete_tombstone_is_byte_identical_and_recoverable(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    content = "important note content\nwith multiple lines\n"
    v.write_text("note.md", content)
    v.delete("note.md")

    assert not (tmp_path / "note.md").exists()
    trash_dir = tmp_path / ".trash"
    assert trash_dir.is_dir()
    trashed_files = list(trash_dir.glob("*.md"))
    assert len(trashed_files) == 1
    assert trashed_files[0].read_text() == content


def test_delete_writes_sidecar_metadata(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    content = "abc123"
    v.write_text("note.md", content)
    v.delete("note.md")

    trash_dir = tmp_path / ".trash"
    sidecars = list(trash_dir.glob("*.meta.json"))
    assert len(sidecars) == 1
    meta = json.loads(sidecars[0].read_text())
    assert meta["original_rel_path"] == "note.md"
    assert meta["byte_count"] == len(content.encode("utf-8"))
    assert "deleted_at" in meta


def test_delete_tombstone_excluded_from_iter_notes(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("keep.md", "---\ntype: entity\n---\nkeep")
    v.write_text("gone.md", "---\ntype: entity\n---\ngone")
    v.delete("gone.md")

    names = {n.name for n in v.iter_notes()}
    assert "keep" in names
    assert "gone" not in names


def test_delete_tombstone_round_trip_restore(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    content = "restore this exactly"
    v.write_text("note.md", content)
    v.delete("note.md")

    trash_dir = tmp_path / ".trash"
    sidecar = next(trash_dir.glob("*.meta.json"))
    meta = json.loads(sidecar.read_text())
    tombstone = trash_dir / sidecar.name.removesuffix(".meta.json")

    # Restore per sidecar's recorded original path.
    restored_path = tmp_path / meta["original_rel_path"]
    os.replace(tombstone, restored_path)

    note = v.load_note(meta["original_rel_path"])
    assert note.content.strip() == content or note.raw_text == content


def test_delete_nested_path_preserved_in_trash_key(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("sub/dir/note.md", "nested content")
    v.delete("sub/dir/note.md")

    trash_dir = tmp_path / ".trash"
    sidecar = next(trash_dir.glob("*.meta.json"))
    meta = json.loads(sidecar.read_text())
    assert meta["original_rel_path"] == "sub/dir/note.md"


def test_tombstone_key_collision_does_not_overwrite_earlier_tombstone(tmp_path: Path, monkeypatch) -> None:
    """The must_fix bug: the tombstone key is
    `<UTC-microsecond-stamp>__<escaped-rel-path>`. Two deletes of the SAME
    path in the SAME microsecond produce the same base key, and the second
    os.replace() into that key would silently clobber the first tombstone
    — breaking mark-never-delete. We force the collision by freezing
    datetime.now() to a fixed instant across two full delete cycles of the
    same path, and assert BOTH tombstones (with their distinct content)
    survive on disk afterward."""
    import weave.vault as vault_mod
    from datetime import datetime as real_datetime

    frozen = real_datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=real_datetime.now().astimezone().tzinfo)

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(vault_mod, "datetime", _FrozenDatetime)

    v = _vault(tmp_path)

    # First generation at path "note.md".
    v.write_text("note.md", "first generation content")
    v.delete("note.md")

    # Second generation at the SAME path, deleted again under the SAME
    # frozen timestamp — this forces the base tombstone key to collide
    # with the first delete's key.
    v.write_text("note.md", "second generation content")
    v.delete("note.md")

    trash_dir = tmp_path / ".trash"
    trashed_files = list(trash_dir.glob("*.md"))
    assert len(trashed_files) == 2, (
        f"expected 2 surviving tombstones after a forced key collision, "
        f"found {len(trashed_files)}: {[p.name for p in trashed_files]}"
    )

    contents = {p.read_text() for p in trashed_files}
    assert contents == {"first generation content", "second generation content"}, (
        "a tombstone was silently overwritten by the colliding second delete"
    )

    # Sidecars must also both survive, one per tombstone.
    sidecars = list(trash_dir.glob("*.meta.json"))
    assert len(sidecars) == 2

    # The two tombstone filenames must differ (collision was resolved).
    names = [p.name for p in trashed_files]
    assert names[0] != names[1]


def test_delete_empty_dir_still_hard_removed(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    (tmp_path / "emptydir").mkdir()
    v.delete("emptydir")
    assert not (tmp_path / "emptydir").exists()
    # Directories don't go to .trash — only files do.


# ---------- no absolute host path leakage ----------

def test_vault_path_error_does_not_leak_absolute_path(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(VaultPathError) as exc_info:
        v._resolve("../../etc/passwd")
    msg = str(exc_info.value)
    assert str(tmp_path) not in msg
    assert not msg.lstrip().startswith("/Users/")


def test_list_dir_not_a_directory_error_no_leak(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "x")
    with pytest.raises(VaultPathError) as exc_info:
        v.list_dir("note.md")
    msg = str(exc_info.value)
    assert str(tmp_path) not in msg


def test_conflict_error_message_no_leak(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.write_text("note.md", "v1")
    _, h = v.read_text_with_hash("note.md")
    v.write_text("note.md", "v2")
    with pytest.raises(VaultConflictError) as exc_info:
        v.write_text_if_unchanged("note.md", "v3", h)
    msg = str(exc_info.value)
    assert str(tmp_path) not in msg
    assert "note.md" in msg
