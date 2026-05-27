"""MCP server exposing Weave Core's 5 verbs as tools.

Run with:
    WEAVE_VAULT_PATH=/path/to/vault python -m weave.mcp_server

Designed for Claude Desktop / Cowork. Zero infra — no Ollama, no DB.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .core import WeaveCore, VaultPathError
from .vault import Vault


def _vault_from_env() -> Vault:
    path = os.environ.get("WEAVE_VAULT_PATH")
    if not path:
        print(
            "ERROR: set WEAVE_VAULT_PATH to your vault directory before launching.",
            file=sys.stderr,
        )
        sys.exit(2)
    return Vault(Path(path).expanduser())


def build_server() -> FastMCP:
    vault = _vault_from_env()
    core = WeaveCore(vault)
    mcp = FastMCP("weave-core")

    @mcp.tool()
    def view(path: str = "", view_start: int | None = None, view_end: int | None = None) -> str:
        """View a file or directory in the vault. Optionally restrict to a line range (1-indexed, inclusive)."""
        view_range = None
        if view_start is not None and view_end is not None:
            view_range = (view_start, view_end)
        return core.view(path, view_range)

    @mcp.tool()
    def create(path: str, content: str) -> str:
        """Create or overwrite a file at the given vault-relative path."""
        return core.create(path, content)

    @mcp.tool()
    def str_replace(path: str, old_str: str, new_str: str) -> str:
        """Replace exactly one occurrence of old_str with new_str in the given file."""
        return core.str_replace(path, old_str, new_str)

    @mcp.tool()
    def insert(path: str, line: int, content: str) -> str:
        """Insert content BEFORE the given 1-indexed line (line=0 prepends)."""
        return core.insert(path, line, content)

    @mcp.tool()
    def delete(path: str) -> str:
        """Delete a file (or empty directory) at the given vault-relative path."""
        return core.delete(path)

    return mcp


def main() -> None:
    mcp = build_server()
    mcp.run()


if __name__ == "__main__":
    main()
