"""MCP tool-surface contract test: verify the 5-verb shape is byte-identical
after write-path hardening — no leaked params (e.g. no `overwrite` on the
`create` tool), same tool names.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from weave.mcp_server import build_server


@pytest.fixture()
def vault_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WEAVE_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("WEAVE_READONLY", raising=False)
    yield tmp_path


def _tool_params(mcp, name: str) -> set[str]:
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    for t in tools:
        if t.name == name:
            props = (t.inputSchema or {}).get("properties", {})
            return set(props.keys())
    raise AssertionError(f"tool {name!r} not registered")


def test_five_verbs_registered(vault_env) -> None:
    mcp = build_server()
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"view", "create", "str_replace", "insert", "delete"}


def test_create_tool_has_no_overwrite_param(vault_env) -> None:
    mcp = build_server()
    params = _tool_params(mcp, "create")
    assert params == {"path", "content"}, (
        f"create tool params changed — expected exactly path/content, got {params}"
    )


def test_str_replace_tool_params_unchanged(vault_env) -> None:
    mcp = build_server()
    params = _tool_params(mcp, "str_replace")
    assert params == {"path", "old_str", "new_str"}


def test_insert_tool_params_unchanged(vault_env) -> None:
    mcp = build_server()
    params = _tool_params(mcp, "insert")
    assert params == {"path", "line", "content"}


def test_delete_tool_params_unchanged(vault_env) -> None:
    mcp = build_server()
    params = _tool_params(mcp, "delete")
    assert params == {"path"}


def test_view_tool_params_unchanged(vault_env) -> None:
    mcp = build_server()
    params = _tool_params(mcp, "view")
    assert params == {"path", "view_start", "view_end"}


def test_readonly_mode_registers_only_view(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WEAVE_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WEAVE_READONLY", "1")
    mcp = build_server()
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"view"}
