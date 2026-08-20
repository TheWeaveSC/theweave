"""Shared vault access layer. Used by both core and pro tiers.

A `Vault` is just a rooted directory of markdown files. Path operations are
sandboxed: any path leaving the root raises `VaultPathError`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import frontmatter


class VaultPathError(ValueError):
    """Raised when a caller tries to read/write outside the vault root."""


@dataclass(frozen=True)
class NoteFault:
    """A note that could not be materialised. `kind` is 'parse' (frontmatter
    is not valid YAML) or 'read' (the bytes could not be read/decoded).

    Faults are DATA, never exceptions swallowed in silence: every consumer of
    iter_notes_safe() gets the list back and is expected to surface it. See
    the 2026-08-13 incident — one unquoted colon in one entity file crashed
    the whole read path for a working session.
    """

    rel_path: str
    kind: str
    error: str


def content_hash(text: str) -> str:
    """THE per-note content-hash convention (sha256, 16 hex). One definition —
    manifest staleness (cortex), hydrate's vault_rev rollup, and any future
    freshness key must share it or they drift apart silently."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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

    def write_text(self, rel: str, text: str) -> None:
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def exists(self, rel: str) -> bool:
        try:
            return self._resolve(rel).exists()
        except VaultPathError:
            return False

    def delete(self, rel: str) -> None:
        p = self._resolve(rel)
        if p.is_dir():
            # only delete empty dirs in core; pro can do more
            p.rmdir()
        else:
            p.unlink()

    def list_dir(self, rel: str = "") -> list[str]:
        p = self._resolve(rel) if rel else self.root
        if not p.is_dir():
            raise VaultPathError(f"not a directory: {rel}")
        return sorted(child.name + ("/" if child.is_dir() else "") for child in p.iterdir())

    # ---------- note iteration ----------

    def note_paths(self) -> Iterator[Path]:
        """THE definition of which files count as notes. Every walk in the
        codebase goes through here.

        One definition on purpose: the parsed walk, the raw walk and doctor's
        sweep must select the IDENTICAL file set or freshness comparison
        reports phantom added/removed entries forever. Before 2026-08-13 this
        rglob-plus-dotfilter was copy-pasted in three places.
        """
        for path in self.root.rglob("*.md"):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                continue
            yield path

    def iter_notes(self) -> Iterator[Note]:
        """Yield every .md note in the vault. NOT canonically ordered (rglob
        order is filesystem-dependent) — byte-stable consumers use
        iter_notes_sorted().

        RAISES on the first malformed note. That is correct for the BUILD
        path, which must not index a half-read vault; read-path callers want
        iter_notes_safe() instead.
        """
        for path in self.note_paths():
            yield self.load_note(self.rel(path))

    def iter_raw_sorted(self) -> list[tuple[str, str]]:
        """(rel_path, raw_text) for every note, rel_path-sorted, WITHOUT
        parsing frontmatter.

        Freshness only ever needed the BYTES. Routing it through a YAML parse
        meant a syntax error in any one note crashed every consumer of
        `source_map` — including live `recall()`, which re-verifies freshness
        on each query. Hashing raw text also makes the derivation manifest
        independent of parse success, so the byte-identical-manifest guarantee
        depends on vault CONTENT alone, as advertised.

        An unreadable file yields a stable sentinel rather than vanishing:
        disappearing from the map would read as 'file deleted' and silently
        drop it from staleness. Loud beats absent.
        """
        out: list[tuple[str, str]] = []
        for path in self.note_paths():
            rel = self.rel(path)
            try:
                out.append((rel, path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError) as e:
                out.append((rel, f"<weave-unreadable:{type(e).__name__}>"))
        out.sort(key=lambda t: t[0])
        return out

    def iter_notes_safe(self) -> tuple[list[Note], list[NoteFault]]:
        """Parsed notes (rel_path-sorted) PLUS the notes that could not be
        parsed. Never raises on a malformed note.

        For read-path callers that must survive a broken file rather than take
        the session down with them. Faults are returned, not swallowed — a
        caller that ignores the second element is the bug, not this method.
        """
        notes: list[Note] = []
        faults: list[NoteFault] = []
        for path in self.note_paths():
            rel = self.rel(path)
            try:
                notes.append(self.load_note(rel))
            except (OSError, UnicodeDecodeError) as e:
                faults.append(NoteFault(rel, "read", f"{type(e).__name__}: {e}"))
            except Exception as e:
                # Keep the WHOLE message, newlines flattened. A YAML
                # ScannerError puts its summary on line 1 and the actual
                # `line N, column M` on line 2 — taking only the first line
                # discards the one detail that tells you where to look.
                detail = " · ".join(p.strip() for p in str(e).splitlines() if p.strip())
                faults.append(NoteFault(rel, "parse", f"{type(e).__name__}: {detail}"))
        notes.sort(key=lambda n: n.rel_path)
        faults.sort(key=lambda f: f.rel_path)
        return notes, faults

    def iter_notes_sorted(self) -> list[Note]:
        """Every note, rel_path-sorted — THE canonical order for anything
        that must be byte-stable across machines (manifests, indexes,
        hydrate). The unsorted-rglob class of bug bit twice (consolidator,
        W0); new consumers call this, not iter_notes()."""
        return sorted(self.iter_notes(), key=lambda n: n.rel_path)

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
