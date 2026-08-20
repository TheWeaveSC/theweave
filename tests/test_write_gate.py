"""Advisory write gate on the MCP write verbs (v1).

Contract under test:
  - an entity-note write gets the conflict proposal APPENDED to the tool
    result (verdict + rationale + per-candidate flags) — the write itself
    always proceeds;
  - WEAVE_WRITE_GATE=0/off bypasses the gate entirely (default is ON);
  - a resolver exception NEVER loses the write — the result comes back as
    if the gate were off (fail-open);
  - non-entity writes pass through untouched.

The gate is deterministic-only (allow_llm=False): no test here needs or
touches an LLM, mock or real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.mcp_server import build_server, _gate_applies, _write_gate_enabled


ENTITY_ACME = """---
type: entity
status: current
owner: marcus
environment: staging
---

# ACME

ACME production database migration. Replication lag stayed under the agreed
threshold after WAL tuning. Migration window confirmed with the platform team.
"""

# Same subject, contradicting frontmatter (owner, environment differ).
ENTITY_ACME_CONFLICT = """---
type: entity
status: current
owner: sarah
environment: production
---

# ACME

ACME production database migration. Replication lag stayed under the agreed
threshold after WAL tuning. Migration window confirmed with the platform team.
"""

UNRELATED_NOTE = """---
type: entity
status: current
---

# Gardening

Tomatoes, compost rotation, and drip irrigation schedules for the allotment.
"""


def _tools(mcp) -> dict:
    return {t.name: t.fn for t in mcp._tool_manager.list_tools()}


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "entity-ACME.md").write_text(ENTITY_ACME, encoding="utf-8")
    (tmp_path / "entities" / "entity-Garden.md").write_text(UNRELATED_NOTE, encoding="utf-8")
    monkeypatch.setenv("WEAVE_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("WEAVE_READONLY", raising=False)
    monkeypatch.delenv("WEAVE_WRITE_GATE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_entity_create_returns_advisory(vault_env):
    tools = _tools(build_server())
    result = tools["create"](path="entities/entity-ACME-v2.md", content=ENTITY_ACME_CONFLICT)
    # the write itself succeeded, and the advisory rode along
    assert result.startswith("created: entities/entity-ACME-v2.md")
    assert (vault_env / "entities" / "entity-ACME-v2.md").read_text(encoding="utf-8") \
        == ENTITY_ACME_CONFLICT
    assert "[write-gate advisory" in result
    assert "verdict:" in result
    assert "rationale:" in result
    # the contradicting sibling is surfaced with its offending keys
    assert "entities/entity-ACME.md" in result
    assert "hard_conflict" in result
    assert "environment" in result and "owner" in result


def test_entity_str_replace_returns_advisory(vault_env):
    tools = _tools(build_server())
    result = tools["str_replace"](
        path="entities/entity-ACME.md", old_str="owner: marcus", new_str="owner: sarah")
    assert result.startswith("replaced 1 occurrence in entities/entity-ACME.md")
    assert "[write-gate advisory" in result
    assert "owner: sarah" in (vault_env / "entities" / "entity-ACME.md").read_text(encoding="utf-8")


def test_dot_prefixed_path_does_not_self_conflict(vault_env):
    """'./entities/entity-X.md' must exclude the same note the index knows as
    'entities/entity-X.md' — otherwise the advisory reports the note
    conflicting with its own just-written self."""
    tools = _tools(build_server())
    result = tools["str_replace"](
        path="./entities/entity-ACME.md", old_str="owner: marcus", new_str="owner: sarah")
    assert result.startswith("replaced 1 occurrence")
    assert "[write-gate advisory" in result
    # the target itself never appears as its own candidate
    assert "entities/entity-ACME.md [" not in result
    assert "verdict: NOOP" not in result


def test_off_switch_bypasses_gate(vault_env, monkeypatch):
    monkeypatch.setenv("WEAVE_WRITE_GATE", "0")
    tools = _tools(build_server())
    result = tools["create"](path="entities/entity-ACME-v2.md", content=ENTITY_ACME_CONFLICT)
    assert result == f"created: entities/entity-ACME-v2.md ({len(ENTITY_ACME_CONFLICT)} chars)"
    assert (vault_env / "entities" / "entity-ACME-v2.md").exists()


@pytest.mark.parametrize("off", ["0", "off", "OFF", "false", "no"])
def test_off_switch_values(monkeypatch, off):
    monkeypatch.setenv("WEAVE_WRITE_GATE", off)
    assert not _write_gate_enabled()


@pytest.mark.parametrize("on", ["", "1", "on", "true", "anything"])
def test_gate_defaults_on(monkeypatch, on):
    if on:
        monkeypatch.setenv("WEAVE_WRITE_GATE", on)
    else:
        monkeypatch.delenv("WEAVE_WRITE_GATE", raising=False)
    assert _write_gate_enabled()


def test_resolver_exception_never_loses_the_write(vault_env, monkeypatch):
    """Fail-open: a gate bug returns the write result as if the gate were off."""
    import weave.pro.conflict as conflict

    def _boom(self, **kwargs):
        raise RuntimeError("simulated gate bug")

    monkeypatch.setattr(conflict.ConflictResolver, "propose", _boom)
    tools = _tools(build_server())
    result = tools["create"](path="entities/entity-ACME-v2.md", content=ENTITY_ACME_CONFLICT)
    assert result == f"created: entities/entity-ACME-v2.md ({len(ENTITY_ACME_CONFLICT)} chars)"
    assert (vault_env / "entities" / "entity-ACME-v2.md").read_text(encoding="utf-8") \
        == ENTITY_ACME_CONFLICT


def test_resolver_init_exception_never_loses_the_write(vault_env, monkeypatch):
    """Even the lazy index build failing must not lose the write."""
    import weave.pro.conflict as conflict

    def _boom_init(self, vault, **kwargs):
        raise RuntimeError("simulated index-build failure")

    monkeypatch.setattr(conflict.ConflictResolver, "__init__", _boom_init)
    tools = _tools(build_server())
    result = tools["create"](path="entities/entity-ACME-v2.md", content=ENTITY_ACME_CONFLICT)
    assert result.startswith("created: entities/entity-ACME-v2.md")
    assert "[write-gate advisory" not in result
    assert (vault_env / "entities" / "entity-ACME-v2.md").exists()


def test_non_entity_write_passes_through(vault_env):
    tools = _tools(build_server())
    body = "---\ndate: '2026-08-19'\ntype: session\n---\n\n# S\nWorked on [[entity-ACME]].\n"
    result = tools["create"](path="sessions/session-2026-08-19-x.md", content=body)
    assert result == f"created: sessions/session-2026-08-19-x.md ({len(body)} chars)"


def test_learninglayer_signal_write_is_gated(vault_env):
    tools = _tools(build_server())
    body = ("---\ndate: '2026-08-19'\ntype: learning-signals\nstatus: current\n---\n\n"
            "# Signals\n- a durable observation\n")
    result = tools["create"](path="LearningLayer/signals-2026-08-19-x.md", content=body)
    assert result.startswith("created: LearningLayer/signals-2026-08-19-x.md")
    assert "[write-gate advisory" in result


def test_gate_applies_path_matching():
    assert _gate_applies("entities/entity-ACME.md")
    assert _gate_applies("./entities/entity-ACME.md")
    assert _gate_applies("entities/./sub/../entity-ACME.md")
    assert _gate_applies("FooVault/entities/entity-ACME-v1.2.8.md")
    assert _gate_applies("entity-Bare.md")
    assert _gate_applies("LearningLayer/signals-2026-08-19-x.md")
    assert not _gate_applies("sessions/session-2026-08-19-x.md")
    assert not _gate_applies("wiki/how-we-work.md")
    assert not _gate_applies("entities/entity-ACME.txt")
