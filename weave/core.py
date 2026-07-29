"""Weave Core — Anthropic 5-verb memory tool shape over a markdown vault.

This is the zero-infra tier. Wraps the vault behind these primitives:
    view, create, str_replace, insert, delete

Designed to be exposed as an MCP server (see weave/mcp_server.py) but the
functions are usable directly from Python too.

Mirrors Anthropic's memory tool docs:
https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool

L5: the write verbs (create/str_replace/insert/delete) each acquire an
advisory cross-machine lease (weave/lease.py) around their L0 write, so
that a competing writer is refused with a named LeaseHeldError rather than
silently racing, and an unreconciled iCloud conflict-copy is surfaced as
ConflictCopyError before any bytes are touched. `view` is read-only and
never leases. See weave/docs/lease.md for exactly what this does and does
not guarantee.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from .lease import ConflictCopyError, LeaseHeldError
from .lease import lease as _lease_cm
from .vault import Vault, VaultConflictError, VaultPathError


class WeaveCore:
    """The five-verb memory primitives. One instance = one vault."""

    def __init__(self, vault: Vault):
        self.vault = vault

    # ---------- L5 advisory lease ----------

    def _lease(self, path: str) -> AbstractContextManager[None]:
        """Acquire an advisory cross-machine lease on `path`, release on exit.

        No-op contextmanager when WEAVE_LEASE is off (see weave/lease.py).
        Raises LeaseHeldError or ConflictCopyError BEFORE any bytes are
        touched; both are ordinary exceptions from the caller's point of
        view — the 5-verb MCP contract shape is unchanged, there are no
        new tools, just new (typed) failure modes on the existing ones.
        """
        return _lease_cm(self.vault, path)

    # ---------- view ----------

    def view(self, path: str = "", view_range: tuple[int, int] | None = None) -> str:
        """Read a file or list a directory.

        - If path is empty or points to a dir, returns a directory listing.
        - If path points to a file, returns its content. With view_range
          (start_line, end_line), returns just those lines (1-indexed, inclusive).
        """
        resolved = self.vault._resolve(path) if path else self.vault.root
        if resolved.is_dir():
            entries = self.vault.list_dir(path)
            header = f"directory: {path or '/'}\n"
            return header + "\n".join(f"  {e}" for e in entries)
        text = self.vault.read_text(path)
        if view_range is None:
            return text
        start, end = view_range
        lines = text.splitlines()
        # 1-indexed, inclusive
        sliced = lines[max(start - 1, 0):end]
        return "\n".join(sliced)

    # ---------- create ----------

    def create(self, path: str, content: str, overwrite: bool = True) -> str:
        """Create (or overwrite) a file at path with given content.

        overwrite=False raises FileExistsError if the file is already
        present, instead of silently clobbering it. Default True preserves
        the original create-or-overwrite contract.

        When overwriting an EXISTING file (the default MCP tool behaviour),
        the prior bytes are first routed through the same tombstone/.trash
        mechanism delete() uses — so an overwrite can never silently
        discard content, it can only be found later in .trash/. The new
        content is then written atomically. The MCP tool surface is
        unaffected: create still exposes only {path, content}.

        L5: acquires an advisory lease on `path` around the write. If
        another writer currently holds it, raises LeaseHeldError naming
        the holder; if an unreconciled iCloud conflict-copy sibling exists,
        raises ConflictCopyError. Retry after either.
        """
        with self._lease(path):
            existed = self.vault.exists(path)
            if existed and not overwrite:
                raise FileExistsError(f"file already exists in vault: {path}")
            if existed:
                self.vault.write_text_tombstoning_prior(path, content)
            else:
                self.vault.write_text(path, content)
            verb = "updated" if existed else "created"
        return f"{verb}: {path} ({len(content)} chars)"

    # ---------- str_replace ----------

    def str_replace(self, path: str, old_str: str, new_str: str) -> str:
        """Replace exactly one occurrence of old_str with new_str.

        Errors if old_str appears 0 or >1 times (matches Anthropic's contract).

        Uses optimistic concurrency: the content hash is captured at read
        time and checked again immediately before the write. If another
        writer changed the file in between, this raises VaultConflictError
        instead of silently clobbering their edit — re-view and retry.

        L5: acquires an advisory lease on `path` around the read+write, so
        a competing writer gets a named LeaseHeldError instead of a race.
        The CAS check above is retained as the last-line backstop inside
        the lease. Raises ConflictCopyError first if an unreconciled
        iCloud conflict-copy sibling exists.
        """
        with self._lease(path):
            if not self.vault.exists(path):
                raise FileNotFoundError(f"no such file in vault: {path}")
            text, content_hash = self.vault.read_text_with_hash(path)
            count = text.count(old_str)
            if count == 0:
                raise ValueError(f"old_str not found in {path}")
            if count > 1:
                raise ValueError(f"old_str matches {count} times in {path}; needs to be unique")
            new_text = text.replace(old_str, new_str, 1)
            self.vault.write_text_if_unchanged(path, new_text, content_hash)
        return f"replaced 1 occurrence in {path}"

    # ---------- insert ----------

    def insert(self, path: str, line: int, content: str) -> str:
        """Insert content at the given 1-indexed line. line=0 prepends.

        Inserts BEFORE the given line. content does not need a trailing newline.

        Uses the same optimistic-concurrency guard as str_replace: a
        concurrent external modification between read and write raises
        VaultConflictError rather than being silently lost.

        L5: acquires an advisory lease on `path` around the read+write (see
        str_replace docstring for the same LeaseHeldError / ConflictCopyError
        semantics).
        """
        with self._lease(path):
            if not self.vault.exists(path):
                raise FileNotFoundError(f"no such file in vault: {path}")
            text, content_hash = self.vault.read_text_with_hash(path)
            lines = text.splitlines(keepends=True)
            if line < 0 or line > len(lines):
                raise ValueError(f"line {line} out of range (0..{len(lines)})")
            if not content.endswith("\n"):
                content = content + "\n"
            lines.insert(line, content)
            self.vault.write_text_if_unchanged(path, "".join(lines), content_hash)
        return f"inserted at line {line} in {path}"

    # ---------- delete ----------

    def delete(self, path: str) -> str:
        """Delete a file (or empty directory) at path.

        L5: acquires an advisory lease on `path` around the delete, same
        LeaseHeldError / ConflictCopyError semantics as the other write verbs.
        """
        with self._lease(path):
            if not self.vault.exists(path):
                raise FileNotFoundError(f"no such path in vault: {path}")
            self.vault.delete(path)
        return f"deleted: {path}"


__all__ = [
    "WeaveCore",
    "VaultPathError",
    "VaultConflictError",
    "LeaseHeldError",
    "ConflictCopyError",
]
