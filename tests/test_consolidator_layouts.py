"""Regression: consolidator must scan sessions under both layouts.

- Flat layout (seed-vault):    sessions/, LearningLayer/, entities/ at vault root.
- Canonical layout (real):     <VaultName>Vault/sessions/, LearningLayer/,
                                <VaultName>Vault/entities/.

Pre-fix, the consolidator hardcoded `startswith("sessions/")`, which made it
silently no-op against any canonical-layout vault — i.e. every real vault.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from weave.pro.consolidator import Consolidator, _path_contains_dir
from weave.vault import Vault


SESSION_BODY = """---
date: '2026-05-15'
type: session
---

# Touched Entity Foo

Worked on [[entity-Foo]].
"""

ENTITY_BODY = """---
type: entity
status: current
valid_from: '2026-01-01'
valid_until: null
---

# Foo
"""

SIGNAL_BODY = """---
date: '2026-05-15'
type: learning-signals
status: current
---

# Signals
- a durable observation
"""


def _write_layout(root: Path, *, nested: bool) -> None:
    if nested:
        sessions_dir = root / "FooVault" / "sessions"
        entities_dir = root / "FooVault" / "entities"
    else:
        sessions_dir = root / "sessions"
        entities_dir = root / "entities"
    learning_dir = root / "LearningLayer"
    for d in (sessions_dir, entities_dir, learning_dir):
        d.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "session-2026-05-15-touch-foo.md").write_text(SESSION_BODY)
    (entities_dir / "entity-Foo.md").write_text(ENTITY_BODY)
    (learning_dir / "signals-2026-05-15-test.md").write_text(SIGNAL_BODY)


@pytest.mark.parametrize("nested", [False, True], ids=["flat", "canonical-nested"])
def test_consolidator_scans_sessions_in_both_layouts(tmp_path: Path, nested: bool) -> None:
    _write_layout(tmp_path, nested=nested)
    v = Vault(tmp_path)
    c = Consolidator(v, window_days=365)
    report = c.build_report(today=date(2026, 5, 27))
    assert len(report.sessions_scanned) == 1, (
        f"expected 1 session scanned under {'nested' if nested else 'flat'} layout, "
        f"got {len(report.sessions_scanned)}"
    )
    assert len(report.signal_files_scanned) == 1
    assert len(report.patches) == 1
    assert report.patches[0].entity_name == "entity-Foo"


def test_consolidator_tolerates_same_day_sessions(tmp_path: Path) -> None:
    """Regression: pre-fix, two sessions sharing a date triggered
    `TypeError: '<' not supported between instances of 'Note' and 'Note'`
    because `recent.sort()` fell back to comparing Note objects."""
    _write_layout(tmp_path, nested=True)
    second = tmp_path / "FooVault" / "sessions" / "session-2026-05-15-second.md"
    second.write_text(SESSION_BODY.replace("Touched Entity Foo", "Also Touched Foo"))
    v = Vault(tmp_path)
    c = Consolidator(v, window_days=365)
    report = c.build_report(today=date(2026, 5, 27))  # must not raise
    assert len(report.sessions_scanned) == 2


def test_path_contains_dir_helper() -> None:
    assert _path_contains_dir("sessions/foo.md", "sessions")
    assert _path_contains_dir("AirVault/sessions/foo.md", "sessions")
    assert _path_contains_dir("a/b/sessions/c.md", "sessions")
    assert not _path_contains_dir("sessions-archive/foo.md", "sessions")
    assert not _path_contains_dir("AirVault/sessionsfoo.md", "sessions")
    assert not _path_contains_dir("entities/foo.md", "sessions")
