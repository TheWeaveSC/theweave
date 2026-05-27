"""Doctor health-check tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.doctor import (
    PASS, WARN, FAIL, INFO,
    _detect_layout,
    check_engine,
    check_environment,
    check_vault,
    run_doctor,
)
from weave.vault import Vault


# ---------- fixtures ----------

ENTITY_BODY = """---
type: entity
status: current
valid_from: '2026-01-01'
valid_until: null
---

# Foo
References [[entity-Bar]].
"""

ENTITY_BAR_BODY = """---
type: entity
status: current
valid_from: '2026-01-01'
valid_until: null
---

# Bar
"""

SESSION_BODY = """---
date: '2026-05-15'
type: session
---

# Touched
Worked on [[entity-Foo]].
"""

SIGNAL_BODY = """---
date: '2026-05-15'
type: learning-signals
status: current
---

# Signals
- a durable observation
"""


def _write_canonical_vault(root: Path) -> None:
    (root / "FooVault" / "sessions").mkdir(parents=True)
    (root / "FooVault" / "entities").mkdir(parents=True)
    (root / "LearningLayer").mkdir(parents=True)
    (root / "FooVault" / "sessions" / "session-2026-05-15-touch.md").write_text(SESSION_BODY)
    (root / "FooVault" / "entities" / "entity-Foo.md").write_text(ENTITY_BODY)
    (root / "FooVault" / "entities" / "entity-Bar.md").write_text(ENTITY_BAR_BODY)
    (root / "LearningLayer" / "signals-2026-05-15-test.md").write_text(SIGNAL_BODY)


def _write_flat_vault(root: Path) -> None:
    (root / "sessions").mkdir()
    (root / "entities").mkdir()
    (root / "LearningLayer").mkdir()
    (root / "sessions" / "session-2026-05-15-touch.md").write_text(SESSION_BODY)
    (root / "entities" / "entity-Foo.md").write_text(ENTITY_BODY)
    (root / "entities" / "entity-Bar.md").write_text(ENTITY_BAR_BODY)
    (root / "LearningLayer" / "signals-2026-05-15-test.md").write_text(SIGNAL_BODY)


# ---------- engine ----------

def test_engine_group_passes_in_test_env() -> None:
    g = check_engine()
    statuses = {c.name: c.status for c in g.checks}
    assert statuses["python"] == PASS
    assert statuses["deps"] == PASS
    assert statuses["entries"] == PASS
    # version is INFO — never fails


def test_environment_group_never_fails() -> None:
    g = check_environment()
    for c in g.checks:
        assert c.status in (PASS, INFO), f"{c.name} unexpectedly {c.status}"


# ---------- layout detection ----------

def test_detect_layout_canonical(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    layout, found = _detect_layout(Vault(tmp_path))
    assert layout == "canonical-nested"
    assert "FooVault/sessions" in found["sessions"]
    assert "FooVault/entities" in found["entities"]
    assert "LearningLayer" in found["LearningLayer"]


def test_detect_layout_flat(tmp_path: Path) -> None:
    _write_flat_vault(tmp_path)
    layout, _ = _detect_layout(Vault(tmp_path))
    assert layout == "flat"


def test_detect_layout_mixed_warns(tmp_path: Path) -> None:
    _write_flat_vault(tmp_path)
    # Add a second sessions/ at a nested location
    (tmp_path / "nested" / "sessions").mkdir(parents=True)
    layout, found = _detect_layout(Vault(tmp_path))
    assert layout == "mixed"
    assert len(found["sessions"]) == 2


# ---------- vault checks ----------

def test_vault_checks_pass_on_clean_canonical(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    g = check_vault(str(tmp_path))
    statuses = {c.name: c.status for c in g.checks}
    assert statuses["path"] == PASS
    assert statuses["layout"] == PASS
    assert statuses["counts"] == PASS
    assert statuses["frontmatter"] == PASS
    assert statuses["p4-reachability"] == PASS
    assert statuses["p2-graph"] == PASS
    assert statuses["bi-temporal"] == PASS


def test_vault_checks_pass_on_clean_flat(tmp_path: Path) -> None:
    _write_flat_vault(tmp_path)
    g = check_vault(str(tmp_path))
    statuses = {c.name: c.status for c in g.checks}
    assert all(s in (PASS, INFO) for s in statuses.values()), statuses


def test_no_vault_path_skips_gracefully() -> None:
    g = check_vault(None)
    assert len(g.checks) == 1 and g.checks[0].status == INFO


def test_broken_frontmatter_warns(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    (tmp_path / "FooVault" / "entities" / "entity-Broken.md").write_text(
        "---\nstatus: [unclosed\n---\n# Broken\n"
    )
    g = check_vault(str(tmp_path))
    fm = next(c for c in g.checks if c.name == "frontmatter")
    assert fm.status == WARN
    assert "Broken" in (fm.detail or "")


def test_session_outside_sessions_dir_warns(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    # Stray session at vault root
    (tmp_path / "session-2026-05-20-stray.md").write_text(SESSION_BODY)
    g = check_vault(str(tmp_path))
    p4 = next(c for c in g.checks if c.name == "p4-reachability")
    assert p4.status == WARN
    assert "session-2026-05-20-stray.md" in (p4.detail or "")


def test_p2_graph_warns_on_high_isolates(tmp_path: Path) -> None:
    # 2 linked entities + 20 isolates → edges > 0 but >50% nodes isolated.
    (tmp_path / "FooVault" / "entities").mkdir(parents=True)
    (tmp_path / "FooVault" / "entities" / "entity-Foo.md").write_text(ENTITY_BODY)
    (tmp_path / "FooVault" / "entities" / "entity-Bar.md").write_text(ENTITY_BAR_BODY)
    isolate_body = ENTITY_BODY.replace("References [[entity-Bar]].", "")
    for i in range(20):
        (tmp_path / "FooVault" / "entities" / f"entity-iso-{i}.md").write_text(isolate_body)
    g = check_vault(str(tmp_path))
    p2 = next(c for c in g.checks if c.name == "p2-graph")
    assert p2.status == WARN
    assert "isolates" in p2.message


def test_p2_graph_fails_on_zero_edges(tmp_path: Path) -> None:
    # All-isolate vault → 0 edges → that's the v1 bug regression case → FAIL.
    (tmp_path / "FooVault" / "entities").mkdir(parents=True)
    isolate_body = ENTITY_BODY.replace("References [[entity-Bar]].", "")
    for i in range(5):
        (tmp_path / "FooVault" / "entities" / f"entity-iso-{i}.md").write_text(isolate_body)
    g = check_vault(str(tmp_path))
    p2 = next(c for c in g.checks if c.name == "p2-graph")
    assert p2.status == FAIL
    assert "BROKEN" in p2.message or "0 edges" in p2.message


def test_low_bi_temporal_coverage_warns(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    # Add 5 entities with no frontmatter — coverage drops below 60%
    for i in range(5):
        (tmp_path / "FooVault" / "entities" / f"entity-bare-{i}.md").write_text(
            "# Bare entity\n"
        )
    g = check_vault(str(tmp_path))
    bt = next(c for c in g.checks if c.name == "bi-temporal")
    assert bt.status == WARN


# ---------- full report ----------

def test_run_doctor_full(tmp_path: Path) -> None:
    _write_canonical_vault(tmp_path)
    report = run_doctor(str(tmp_path), include_mcp=False)
    assert report.failures() == 0
    text = report.to_text()
    assert "[Engine]" in text and "[Vault]" in text and "[Environment]" in text
    assert "[MCP]" not in text  # only when --check-mcp


def test_run_doctor_with_mcp_check(tmp_path: Path) -> None:
    report = run_doctor(None, include_mcp=True)
    group_names = {g.name for g in report.groups}
    assert "MCP" in group_names
