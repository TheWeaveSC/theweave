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
