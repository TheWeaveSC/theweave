"""Claude config path resolution + atomic JSON merge writer.

HARD TEST CONSTRAINT: every function here that touches a real path takes
that path as an explicit argument. Nothing in this module calls
`Path.home()` except the two `default_*_config_path()` helpers, which are
only ever invoked when the caller did NOT pass an override — i.e. the
override is the seam that keeps tests off the real machine config.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (tempfile + os.replace, same dir).

    Mirrors Vault._atomic_write's idiom but standalone, since config files
    live outside any vault.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def default_desktop_config_path() -> Path:
    """OS-specific default location of claude_desktop_config.json.

    Only called when the caller passed no --claude-desktop-config override.
    """
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA", str(home / "AppData/Roaming"))
        return Path(appdata) / "Claude/claude_desktop_config.json"
    # Linux and everything else
    return home / ".config/Claude/claude_desktop_config.json"


def default_code_config_path() -> Path:
    """Default location of Claude Code's ~/.claude.json.

    Only called when the caller passed no --claude-code-config override.
    """
    return Path.home() / ".claude.json"


def weave_core_mcp_block(python_path: str, vault_path: str) -> dict:
    """The exact mcpServers.weave-core block shape (matches the snippet doc)."""
    return {
        "command": python_path,
        "args": ["-m", "weave.mcp_server"],
        "env": {"WEAVE_VAULT_PATH": vault_path},
    }


def load_json_config(path: Path) -> dict:
    """Load a JSON config file, returning {} if it doesn't exist yet."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def diff_mcp_entry(existing: dict | None, desired: dict) -> str:
    """Idempotency probe for a single mcpServers.weave-core entry.

    Returns one of: "create" (no entry yet), "skip-exists" (entry already
    matches desired), "update" (entry exists but differs).
    """
    if existing is None:
        return "create"
    if existing == desired:
        return "skip-exists"
    return "update"


def merge_mcp_server(config: dict, server_name: str, block: dict) -> dict:
    """Return a NEW config dict with mcpServers[server_name] = block, preserving
    every other top-level key and every other mcpServers entry.
    """
    new_config = dict(config)
    servers = dict(new_config.get("mcpServers") or {})
    servers[server_name] = block
    new_config["mcpServers"] = servers
    return new_config


def claude_binary_available() -> str | None:
    """Path to the `claude` binary on PATH, or None. Isolated in its own
    function so tests can monkeypatch shutil.which and assert it is never
    consulted when a code-config override is supplied.
    """
    return shutil.which("claude")


def _default_subprocess_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def run_claude_mcp_add(
    claude_bin: str,
    vault_path: str,
    python_path: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess] = _default_subprocess_runner,
) -> subprocess.CompletedProcess:
    """Shell out to `claude mcp add weave-core --scope user --env WEAVE_VAULT_PATH=<vault> -- <python> -m weave.mcp_server`.

    Only ever called when a real `claude` binary was detected, no
    --claude-code-config override was supplied, AND the idempotency probe
    (diff_mcp_entry) shows no equivalent weave-core entry already exists —
    the caller in installer/init.py is responsible for that gating.

    --scope user pins the entry to the user-level config (~/.claude.json),
    matching where the JSON-merge fallback writes; the CLI default of
    `--scope local` would instead write a project/cwd-scoped entry that
    diverges from the fallback path.

    `runner` is an injectable seam (defaults to a real subprocess.run call)
    so tests can exercise this branch with a fake runner instead of
    shelling out to a real `claude` binary.
    """
    return runner(
        [
            claude_bin, "mcp", "add", "weave-core",
            "--scope", "user",
            "--env", f"WEAVE_VAULT_PATH={vault_path}",
            "--",
            python_path, "-m", "weave.mcp_server",
        ]
    )


__all__ = [
    "atomic_write_text",
    "default_desktop_config_path",
    "default_code_config_path",
    "weave_core_mcp_block",
    "load_json_config",
    "diff_mcp_entry",
    "merge_mcp_server",
    "claude_binary_available",
    "run_claude_mcp_add",
]
