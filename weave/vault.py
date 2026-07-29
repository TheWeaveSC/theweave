"""Shared vault access layer. Used by both core and pro tiers.

A `Vault` is just a rooted directory of markdown files. Path operations are
sandboxed: any path leaving the root raises `VaultPathError`.

NOTE on L5 (weave/lease.py): the advisory cross-machine lease deliberately
wraps the WeaveCore *verb* layer (create/str_replace/insert/delete in
core.py), NOT these primitives. installer/scaffold.py and internal sidecar
writes (e.g. `.trash/` tombstone sidecars) call `_atomic_write` /
`write_text` directly and must stay lease-free — they are single-writer
first-run/bookkeeping paths, not the LD#17 one-writer-per-project surface.
`_atomic_write` itself IS reused by lease.py to write the lease sidecar
file, so a torn lease is impossible for the same reason a torn note is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import frontmatter


class VaultPathError(ValueError):
    """Raised when a caller tries to read/write outside the vault root."""


class VaultConflictError(RuntimeError):
    """Raised when a guarded write detects the on-disk file changed since it was read.

    This is the loud, catchable replacement for a silent lost-update: the
    caller re-read a note, computed an edit, and by the time it tried to
    write, someone else's bytes were already on disk.
    """


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


@dataclass
class Note:
    """A parsed markdown note inside the vault."""

    path: Path                # absolute path
    rel_path: str             # path relative to vault root, forward slashes
    name: str                 # stem (e.g. "entity-ACME")
    metadata: dict            # parsed frontmatter
    content: str              # markdown body (no frontmatter)
    raw_text: str             # full file text including frontmatter

    def wikilinks(self) -> list[str]:
        """Wikilink targets referenced by this note (just the base names).

        Scans both the markdown body AND frontmatter scalar/list values, so
        e.g. `touches: ["[[entity-X]]"]` in YAML counts as an edge.
        """
        targets: list[str] = []
        targets.extend(m.group(1).strip() for m in WIKILINK_RE.finditer(self.content))
        for v in _walk_strings(self.metadata):
            targets.extend(m.group(1).strip() for m in WIKILINK_RE.finditer(v))
        return targets


def _walk_strings(obj) -> Iterator[str]:
    """Yield every string value found anywhere inside obj (dict/list/scalar)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _walk_strings(v)


class Vault:
    """A rooted markdown vault. All path arguments are vault-relative."""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise VaultPathError(f"vault root does not exist or is not a dir: {self.root}")

    # ---------- path safety ----------

    def _resolve(self, rel: str) -> Path:
        """Resolve a vault-relative path, refusing anything outside root."""
        rel = rel.lstrip("/").replace("\\", "/")
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as e:
            raise VaultPathError(f"path escapes vault root: {rel}") from e
        return candidate

    def rel(self, abs_path: Path) -> str:
        return abs_path.resolve().relative_to(self.root).as_posix()

    # ---------- I/O primitives ----------

    def read_text(self, rel: str) -> str:
        p = self._resolve(rel)
        return p.read_text(encoding="utf-8")

    def read_text_with_hash(self, rel: str) -> tuple[str, str]:
        """Read a file's text plus a sha256 hex digest of its content.

        The hash is a free version token: it can never drift out of sync
        with the content it versions, unlike an mtime (which iCloud's file
        provider can rewrite without a local write) or a separate counter.
        """
        text = self.read_text(rel)
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _atomic_write(self, p: Path, text: str) -> None:
        """Write `text` to path `p` atomically.

        Writes to a sibling tempfile in the SAME directory as `p` (required
        for os.replace to be atomic — same filesystem), flushes + fsyncs the
        fd, then os.replace()s it into place. On any exception the tempfile
        is unlinked so a crash never leaves a stray partial file behind, and
        the destination is left as either fully-old or fully-new content —
        never torn.
        """
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=p.parent, prefix=f".{p.name}.", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        else:
            # Best-effort: fsync the parent directory so the rename itself
            # is durable across a crash. Not supported on all platforms
            # (e.g. Windows) — failure here is not fatal to correctness of
            # the already-atomic replace.
            try:
                dirfd = os.open(p.parent, os.O_RDONLY)
                try:
                    os.fsync(dirfd)
                finally:
                    os.close(dirfd)
            except OSError:
                pass

    def write_text(self, rel: str, text: str) -> None:
        p = self._resolve(rel)
        self._atomic_write(p, text)

    def write_text_tombstoning_prior(self, rel: str, text: str) -> None:
        """Write `text` to `rel`, but if a file already exists there, first
        route its prior bytes through the same tombstone/.trash mechanism
        `delete()` uses, THEN write the new content atomically.

        This closes the create()-with-overwrite data-loss hole: overwriting
        an existing note used to discard the prior bytes with no recovery
        path. Now every overwrite leaves a recoverable tombstone of what was
        there before, same as an explicit delete would.

        If `rel` does not currently exist, this is identical to
        `write_text()` — nothing to tombstone.
        """
        p = self._resolve(rel)
        if p.exists() and not p.is_dir():
            self._tombstone_file(p, rel)
        self._atomic_write(p, text)

    def write_text_if_unchanged(self, rel: str, text: str, expected_hash: str) -> None:
        """Atomically write `text` to `rel`, but only if the on-disk content's
        hash still matches `expected_hash`.

        Re-reads and re-hashes immediately before the atomic replace, so the
        window for a lost update shrinks from unbounded (iCloud sync lag)
        down to the few milliseconds between that re-hash and os.replace.
        Raises VaultConflictError if the file changed underneath the caller.
        """
        p = self._resolve(rel)
        if p.exists():
            current = p.read_text(encoding="utf-8")
            current_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if current_hash != expected_hash:
                raise VaultConflictError(
                    f"{rel} changed on disk since it was read; re-view and retry"
                )
        self._atomic_write(p, text)

    def exists(self, rel: str) -> bool:
        try:
            return self._resolve(rel).exists()
        except VaultPathError:
            return False

    def _tombstone_key(self, trash_dir: Path, rel: str) -> str:
        """Build a collision-free tombstone key for `rel` inside `trash_dir`.

        Base key is `<UTC-microsecond-stamp>__<escaped-rel-path>`. Two
        tombstones for the same path landing in the same microsecond (two
        rapid deletes, or an overwrite-tombstone racing a delete-tombstone)
        would otherwise collide on this base key and the later os.replace()
        into `dest` would silently clobber the earlier tombstone — breaking
        the mark-never-delete guarantee. To prevent that, if the base key is
        already taken on disk we append a short random uniqueness suffix
        (inserted before the trailing file extension, so tombstone keys keep
        looking like `*.md` for glob-based tooling/tests) and retry until we
        find a free slot, so no tombstone ever overwrites another one.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_rel = rel.lstrip("/").replace("/", "%2F")
        base_key = f"{stamp}__{safe_rel}"
        base_path = Path(base_key)
        stem, suffix = base_path.stem, base_path.suffix
        key = base_key
        while (trash_dir / key).exists() or (trash_dir / f"{key}.meta.json").exists():
            key = f"{stem}__{secrets.token_hex(4)}{suffix}"
        return key

    def _tombstone_file(self, p: Path, rel: str) -> None:
        """Move an existing on-disk file `p` (vault-relative path `rel`) into
        the `.trash/` tombstone, with a sidecar recording its origin.

        Shared by `delete()` and by `create()`'s overwrite path (see
        WeaveCore.create in core.py) so that clobbering existing bytes is
        never possible without first routing them through this recoverable
        mark-never-delete mechanism.
        """
        trash_dir = self.root / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        key = self._tombstone_key(trash_dir, rel)
        dest = trash_dir / key

        size = p.stat().st_size
        os.replace(p, dest)

        sidecar = trash_dir / f"{key}.meta.json"
        meta = {
            "original_rel_path": rel,
            "deleted_at": key.split("__", 1)[0],
            "byte_count": size,
        }
        try:
            self._atomic_write(sidecar, json.dumps(meta, indent=2))
        except OSError:
            # Sidecar is best-effort; the note itself is still recoverable
            # by filename (the key encodes the original rel path).
            pass

    def delete(self, rel: str) -> None:
        """Soft-delete: move the file into a vault-root `.trash/` tombstone.

        `.trash/` is dot-prefixed, so it is already excluded from
        iter_notes(), the doctor sweep, and the wikilink graph (all skip
        dotted path parts) — the note vanishes from every live view, yet the
        bytes are fully recoverable, honouring the vault's bi-temporal
        mark-never-delete rule with zero extra infra.

        Empty directories are still hard-removed (rmdir refuses non-empty
        dirs anyway, so this can't silently eat vault content).
        """
        p = self._resolve(rel)
        if p.is_dir():
            # only delete empty dirs in core; pro can do more
            p.rmdir()
            return

        self._tombstone_file(p, rel)

    def list_dir(self, rel: str = "") -> list[str]:
        p = self._resolve(rel) if rel else self.root
        if not p.is_dir():
            raise VaultPathError(f"not a directory: {rel}")
        return sorted(child.name + ("/" if child.is_dir() else "") for child in p.iterdir())

    # ---------- note iteration ----------

    def iter_notes(self) -> Iterator[Note]:
        """Yield every .md note in the vault."""
        for path in self.root.rglob("*.md"):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                continue
            yield self.load_note(self.rel(path))

    def load_note(self, rel: str) -> Note:
        p = self._resolve(rel)
        raw = p.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        return Note(
            path=p,
            rel_path=self.rel(p),
            name=p.stem,
            metadata=dict(post.metadata),
            content=post.content,
            raw_text=raw,
        )

    def find_note_by_name(self, name: str) -> Note | None:
        """Find a note by its stem name (the wikilink target form)."""
        name = name.strip()
        for note in self.iter_notes():
            if note.name == name:
                return note
        return None
