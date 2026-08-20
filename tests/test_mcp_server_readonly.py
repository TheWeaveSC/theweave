"""Governance: WEAVE_READONLY gates the write verbs at the tool surface.

A peer-vault instance must expose ONLY `view` — the write verbs are never
registered, so writing to the wrong vault is impossible by construction
(not merely discouraged). This is the enforcement behind write-home/read-peer.
"""

from __future__ import annotations

import pytest

from weave.mcp_server import build_server

WRITE_VERBS = {"create", "str_replace", "insert", "delete"}
READ_VERBS = {"view", "hydrate", "recall"}  # all registered before the read-only guard


def _tool_names(mcp) -> set[str]:
    return {t.name for t in mcp._tool_manager.list_tools()}


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WEAVE_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("WEAVE_READONLY", raising=False)
    return tmp_path


def test_default_is_read_write(vault_env, monkeypatch):
    """No WEAVE_READONLY -> all 5 verbs (backward compatible)."""
    names = _tool_names(build_server())
    assert "view" in names
    assert WRITE_VERBS <= names


def test_readonly_exposes_only_read_verbs(vault_env, monkeypatch):
    """WEAVE_READONLY=1 -> only the read verbs (view + hydrate); write verbs absent."""
    monkeypatch.setenv("WEAVE_READONLY", "1")
    names = _tool_names(build_server())
    assert names == READ_VERBS
    assert not (WRITE_VERBS & names)


def test_readonly_peer_can_hydrate_but_not_write(vault_env, monkeypatch):
    """A read-only peer exposes hydrate (read-only verb) and NO write verbs."""
    monkeypatch.setenv("WEAVE_READONLY", "1")
    names = _tool_names(build_server())
    assert "hydrate" in names
    assert not (WRITE_VERBS & names)


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", " Yes "])
def test_readonly_truthy_values(vault_env, monkeypatch, truthy):
    monkeypatch.setenv("WEAVE_READONLY", truthy)
    assert _tool_names(build_server()) == READ_VERBS


@pytest.mark.parametrize("falsy", ["0", "false", "no", "", "off"])
def test_readonly_falsy_values_stay_read_write(vault_env, monkeypatch, falsy):
    monkeypatch.setenv("WEAVE_READONLY", falsy)
    assert WRITE_VERBS <= _tool_names(build_server())
