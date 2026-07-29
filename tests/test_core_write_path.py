"""WeaveCore 5-verb write-path hardening tests.

Covers: create() overwrite guard, str_replace/insert CAS conflict detection
(the exact lost-update scenario from the arch-audit), and happy-path
compatibility (return strings unchanged).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.core import WeaveCore, VaultConflictError
from weave.vault import Vault


def _core(tmp_path: Path) -> WeaveCore:
    return WeaveCore(Vault(tmp_path))


# ---------- create() overwrite guard ----------

def test_create_default_overwrites_existing_file(tmp_path: Path) -> None:
    core = _core(tmp_path)
    msg1 = core.create("note.md", "v1")
    assert msg1 == "created: note.md (2 chars)"
    msg2 = core.create("note.md", "v2 longer")
    assert msg2 == "updated: note.md (9 chars)"
    assert (tmp_path / "note.md").read_text() == "v2 longer"


def test_create_overwrite_false_raises_on_existing_file(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.create("note.md", "v1")
    with pytest.raises(FileExistsError):
        core.create("note.md", "v2", overwrite=False)
    # Original content preserved.
    assert (tmp_path / "note.md").read_text() == "v1"


def test_create_overwrite_false_succeeds_on_new_file(tmp_path: Path) -> None:
    core = _core(tmp_path)
    msg = core.create("note.md", "v1", overwrite=False)
    assert msg == "created: note.md (2 chars)"


def test_create_overwrite_of_existing_file_leaves_recoverable_tombstone(tmp_path: Path) -> None:
    """The must_fix bug: create() with overwrite=True (the default the MCP
    tool uses) used to discard the prior bytes with no way to recover them.
    Now an overwrite of an EXISTING file must first tombstone the prior
    content into .trash/ (same mechanism delete() uses), THEN write the new
    content. The MCP tool surface stays {path, content} — this is purely an
    internal safety net."""
    core = _core(tmp_path)
    original = "original important content\nline two\n"
    core.create("note.md", original)

    msg = core.create("note.md", "brand new content")
    assert msg == "updated: note.md (17 chars)"

    # Live file has the new content.
    assert (tmp_path / "note.md").read_text() == "brand new content"

    # The prior bytes must be recoverable from .trash/ — byte-identical.
    trash_dir = tmp_path / ".trash"
    assert trash_dir.is_dir()
    trashed_files = [p for p in trash_dir.glob("*.md")]
    assert len(trashed_files) == 1
    assert trashed_files[0].read_text() == original

    # Sidecar metadata records where it came from.
    sidecars = list(trash_dir.glob("*.meta.json"))
    assert len(sidecars) == 1
    import json as _json
    meta = _json.loads(sidecars[0].read_text())
    assert meta["original_rel_path"] == "note.md"
    assert meta["byte_count"] == len(original.encode("utf-8"))


def test_create_of_new_file_does_not_tombstone_anything(tmp_path: Path) -> None:
    """No prior file existed, so create() must behave exactly as before —
    no .trash/ directory should even be created."""
    core = _core(tmp_path)
    core.create("brand-new.md", "hello")
    assert not (tmp_path / ".trash").exists()


def test_create_overwrite_twice_leaves_two_recoverable_tombstones(tmp_path: Path) -> None:
    """Overwriting the same path repeatedly must tombstone EVERY prior
    version, not just the most recent one — mark-never-delete applies to
    every generation, not just the last."""
    core = _core(tmp_path)
    core.create("note.md", "version 1")
    core.create("note.md", "version 2")
    core.create("note.md", "version 3")

    assert (tmp_path / "note.md").read_text() == "version 3"

    trash_dir = tmp_path / ".trash"
    trashed_contents = {p.read_text() for p in trash_dir.glob("*.md")}
    assert trashed_contents == {"version 1", "version 2"}


# ---------- str_replace happy path unchanged ----------

def test_str_replace_happy_path_return_string_unchanged(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.create("note.md", "hello world")
    msg = core.str_replace("note.md", "world", "there")
    assert msg == "replaced 1 occurrence in note.md"
    assert (tmp_path / "note.md").read_text() == "hello there"


def test_str_replace_zero_matches_raises_value_error(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.create("note.md", "hello world")
    with pytest.raises(ValueError):
        core.str_replace("note.md", "missing", "x")


def test_str_replace_multiple_matches_raises_value_error(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.create("note.md", "aa aa")
    with pytest.raises(ValueError):
        core.str_replace("note.md", "aa", "bb")


def test_str_replace_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    core = _core(tmp_path)
    with pytest.raises(FileNotFoundError):
        core.str_replace("missing.md", "a", "b")


# ---------- insert happy path unchanged ----------

def test_insert_happy_path_return_string_unchanged(tmp_path: Path) -> None:
    core = _core(tmp_path)
    core.create("note.md", "line1\nline2\n")
    msg = core.insert("note.md", 1, "inserted")
    assert msg == "inserted at line 1 in note.md"
    assert (tmp_path / "note.md").read_text() == "line1\ninserted\nline2\n"


# ---------- CAS conflict detection: the exact arch-audit lost-update scenario ----------

def test_str_replace_lost_update_detected(tmp_path: Path) -> None:
    """Instance A captures state at read; instance B completes a full
    str_replace + write; A's write must raise VaultConflictError, and B's
    edit must survive untouched. This is the exact race the arch-audit
    flagged: two writers on an async-synced vault with no lease."""
    core_a = _core(tmp_path)
    core_b = WeaveCore(Vault(tmp_path))

    core_a.create("note.md", "shared original content")

    # Both A and B "read" (in real life this happens via view()/MCP calls;
    # here we simulate by having each instance independently read+hash by
    # calling into vault directly for A's captured state).
    text_a, hash_a = core_a.vault.read_text_with_hash("note.md")

    # B completes its full str_replace first (its own internal read+write).
    msg_b = core_b.str_replace("note.md", "original", "B-EDITED")
    assert msg_b == "replaced 1 occurrence in note.md"

    # A now tries to apply its own edit based on the STALE hash it captured
    # before B's write. We drive this through the guarded write directly
    # since str_replace() re-reads internally (and would otherwise no
    # longer find "original" in the now-B-edited text, giving a different
    # error). To reproduce the true lost-update path, use write_text_if_unchanged.
    stale_new_text = text_a.replace("original", "A-EDITED")
    with pytest.raises(VaultConflictError):
        core_a.vault.write_text_if_unchanged("note.md", stale_new_text, hash_a)

    # B's edit must have survived.
    assert (tmp_path / "note.md").read_text() == "shared B-EDITED content"


def test_str_replace_full_race_via_two_core_instances(tmp_path: Path) -> None:
    """More direct simulation: A's str_replace call is interrupted by B's
    write landing in between A's internal read and A's internal write."""
    core_a = WeaveCore(Vault(tmp_path))
    core_b = WeaveCore(Vault(tmp_path))
    core_a.create("note.md", "original content here")

    # Manually interleave: capture A's read+hash (mimicking the first half
    # of str_replace), then have B fully complete a str_replace, then
    # finish A's write using the stale hash.
    vault_a = core_a.vault
    text, h = vault_a.read_text_with_hash("note.md")
    new_text = text.replace("original", "A-WINS")

    core_b.str_replace("note.md", "content", "B-WINS")

    with pytest.raises(VaultConflictError):
        vault_a.write_text_if_unchanged("note.md", new_text, h)

    assert "B-WINS" in (tmp_path / "note.md").read_text()
    assert "A-WINS" not in (tmp_path / "note.md").read_text()


def test_insert_conflict_detected(tmp_path: Path) -> None:
    core_a = WeaveCore(Vault(tmp_path))
    core_b = WeaveCore(Vault(tmp_path))
    core_a.create("note.md", "line1\nline2\n")

    vault_a = core_a.vault
    text, h = vault_a.read_text_with_hash("note.md")

    core_b.insert("note.md", 1, "B-inserted")

    lines = text.splitlines(keepends=True)
    lines.insert(0, "A-inserted\n")
    with pytest.raises(VaultConflictError):
        vault_a.write_text_if_unchanged("note.md", "".join(lines), h)

    final = (tmp_path / "note.md").read_text()
    assert "B-inserted" in final
    assert "A-inserted" not in final


def test_str_replace_no_conflict_when_single_writer(tmp_path: Path) -> None:
    """Sanity: with no concurrent writer, str_replace works exactly as
    before — the hash guard is invisible on the happy path."""
    core = WeaveCore(Vault(tmp_path))
    core.create("note.md", "alpha beta gamma")
    msg1 = core.str_replace("note.md", "beta", "BETA")
    assert msg1 == "replaced 1 occurrence in note.md"
    msg2 = core.str_replace("note.md", "gamma", "GAMMA")
    assert msg2 == "replaced 1 occurrence in note.md"
    assert (tmp_path / "note.md").read_text() == "alpha BETA GAMMA"


# ---------- delete happy path + tombstone integration ----------

def test_delete_happy_path_return_string_unchanged(tmp_path: Path) -> None:
    core = WeaveCore(Vault(tmp_path))
    core.create("note.md", "x")
    msg = core.delete("note.md")
    assert msg == "deleted: note.md"
    assert not (tmp_path / "note.md").exists()


def test_delete_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    core = WeaveCore(Vault(tmp_path))
    with pytest.raises(FileNotFoundError):
        core.delete("missing.md")


def test_view_still_works_after_hardening(tmp_path: Path) -> None:
    core = WeaveCore(Vault(tmp_path))
    core.create("note.md", "line1\nline2\nline3\n")
    assert core.view("note.md") == "line1\nline2\nline3\n"
    assert core.view("note.md", view_range=(2, 2)) == "line2"
