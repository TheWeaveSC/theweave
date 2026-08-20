"""v0.5 item 17 — `weave lint`, the frontmatter pre-flight validator.

Catches a bad edit at session end instead of during the nightly job. The
motivating outage class is a single unquoted YAML scalar that runs for days
because nothing points at the file. Exit code = fault count, so a hook or CI
step can gate on it.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from weave.cli import cli

GOOD = "---\ntitle: Good\ntype: entity\n---\n\nBody.\n"
# The exact defect class from the incident.
BAD = ("---\ntitle: CTL3\n"
       "progress: v4.0 CERTIFIED LIVE 2025-06-01. NEXT PHASE: two-entity merge\n"
       "---\n\nBody.\n")
# The same note with the scalar quoted — i.e. the actual repair.
FIXED = ("---\ntitle: CTL3\n"
         "progress: 'v4.0 CERTIFIED LIVE 2025-06-01. NEXT PHASE: two-entity merge'\n"
         "---\n\nBody.\n")


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault" / "HomeVault" / "entities"
    d.mkdir(parents=True)
    (d / "entity-good.md").write_text(GOOD, encoding="utf-8")
    return tmp_path / "vault"


def _run(vault_dir, *extra):
    return CliRunner().invoke(cli, ["lint", "--vault", str(vault_dir), *extra])


def test_clean_vault_exits_zero(vault_dir):
    res = _run(vault_dir)
    assert res.exit_code == 0
    assert "0 faults" in res.output


def test_fault_exits_nonzero_and_names_the_file(vault_dir):
    (vault_dir / "HomeVault" / "entities" / "entity-bad.md").write_text(
        BAD, encoding="utf-8")
    res = _run(vault_dir)
    assert res.exit_code == 1
    assert "entity-bad.md" in res.output
    assert "ScannerError" in res.output


def test_hint_points_at_the_offending_line_and_names_the_defect(vault_dir):
    """The whole value of this command. 'your YAML is broken' costs a hunt
    through 600 files; naming the line costs ten seconds."""
    (vault_dir / "HomeVault" / "entities" / "entity-bad.md").write_text(
        BAD, encoding="utf-8")
    out = _run(vault_dir).output
    assert "3: progress: v4.0 CERTIFIED LIVE" in out   # the actual source line
    assert "single quotes" in out                       # the actual remedy


def test_exit_code_counts_faults(vault_dir):
    ents = vault_dir / "HomeVault" / "entities"
    for i in range(3):
        (ents / f"entity-bad{i}.md").write_text(BAD, encoding="utf-8")
    assert _run(vault_dir).exit_code == 3


def test_paths_mode_is_machine_readable(vault_dir):
    """--paths feeds a hook: bare rel_paths, nothing else on stdout."""
    (vault_dir / "HomeVault" / "entities" / "entity-bad.md").write_text(
        BAD, encoding="utf-8")
    res = _run(vault_dir, "--paths")
    assert res.exit_code == 1
    assert res.output.strip() == "HomeVault/entities/entity-bad.md"


def test_repairing_the_file_clears_the_fault(vault_dir):
    bad = vault_dir / "HomeVault" / "entities" / "entity-bad.md"
    bad.write_text(BAD, encoding="utf-8")
    assert _run(vault_dir).exit_code == 1
    bad.write_text(FIXED, encoding="utf-8")
    assert _run(vault_dir).exit_code == 0
