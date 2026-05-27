"""Weave Core — Anthropic 5-verb memory tool shape over a markdown vault.

This is the zero-infra tier. Wraps the vault behind these primitives:
    view, create, str_replace, insert, delete

Designed to be exposed as an MCP server (see weave/mcp_server.py) but the
functions are usable directly from Python too.

Mirrors Anthropic's memory tool docs:
https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool
"""

from __future__ import annotations

from .vault import Vault, VaultPathError


class WeaveCore:
    """The five-verb memory primitives. One instance = one vault."""

    def __init__(self, vault: Vault):
        self.vault = vault

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

    def create(self, path: str, content: str) -> str:
        """Create (or overwrite) a file at path with given content."""
        existed = self.vault.exists(path)
        self.vault.write_text(path, content)
        verb = "updated" if existed else "created"
        return f"{verb}: {path} ({len(content)} chars)"

    # ---------- str_replace ----------

    def str_replace(self, path: str, old_str: str, new_str: str) -> str:
        """Replace exactly one occurrence of old_str with new_str.

        Errors if old_str appears 0 or >1 times (matches Anthropic's contract).
        """
        if not self.vault.exists(path):
            raise FileNotFoundError(f"no such file in vault: {path}")
        text = self.vault.read_text(path)
        count = text.count(old_str)
        if count == 0:
            raise ValueError(f"old_str not found in {path}")
        if count > 1:
            raise ValueError(f"old_str matches {count} times in {path}; needs to be unique")
        new_text = text.replace(old_str, new_str, 1)
        self.vault.write_text(path, new_text)
        return f"replaced 1 occurrence in {path}"

    # ---------- insert ----------

    def insert(self, path: str, line: int, content: str) -> str:
        """Insert content at the given 1-indexed line. line=0 prepends.

        Inserts BEFORE the given line. content does not need a trailing newline.
        """
        if not self.vault.exists(path):
            raise FileNotFoundError(f"no such file in vault: {path}")
        text = self.vault.read_text(path)
        lines = text.splitlines(keepends=True)
        if line < 0 or line > len(lines):
            raise ValueError(f"line {line} out of range (0..{len(lines)})")
        if not content.endswith("\n"):
            content = content + "\n"
        lines.insert(line, content)
        self.vault.write_text(path, "".join(lines))
        return f"inserted at line {line} in {path}"

    # ---------- delete ----------

    def delete(self, path: str) -> str:
        """Delete a file (or empty directory) at path."""
        if not self.vault.exists(path):
            raise FileNotFoundError(f"no such path in vault: {path}")
        self.vault.delete(path)
        return f"deleted: {path}"


__all__ = ["WeaveCore", "VaultPathError"]
