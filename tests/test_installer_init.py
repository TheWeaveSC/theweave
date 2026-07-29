"""L4 one-click installer tests — `weave-cli init` / weave.installer.

HARD TEST CONSTRAINT: every test builds the vault under tempfile.mkdtemp()
and points --claude-desktop-config / --claude-code-config at files under a
SEPARATE tempdir. No test reads Path.home(), the real Claude config, or
the real vault. Tests call run_init(opts) directly (no Click runner) so
they can inspect the returned InstallPlan/exit code without touching stdin.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from weave.doctor import run_doctor
from weave.installer import InstallOptions, run_init
from weave.installer.init import build_plan
from weave.team.validator import validate_team
from weave.vault import Vault


# ---------- fixtures ----------

def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp())


def _opts(**kwargs) -> InstallOptions:
    vault_dir = kwargs.pop("vault", None) or str(_tmp_dir() / "vault")
    cfg_dir = _tmp_dir()
    defaults = dict(
        vault=vault_dir,
        claude_desktop_config=str(cfg_dir / "desktop.json"),
        claude_code_config=str(cfg_dir / "code.json"),
        today=date(2026, 7, 1),
        yes=True,
    )
    defaults.update(kwargs)
    return InstallOptions(**defaults)


# ---------- scaffold ----------

def test_scaffold_creates_layout() -> None:
    opts = _opts()
    rc = run_init(opts)
    assert rc == 0
    root = Path(opts.vault)
    assert (root / "entities").is_dir()
    assert (root / "LearningLayer").is_dir()
    assert (root / "sessions").is_dir()
    boot = (root / "BOOT.md").read_text(encoding="utf-8")
    assert "Basename-only wikilinks" in boot
    assert "Machine-suffixed LearningLayer filenames" in boot
    for phase in ("Intake", "Plan", "Execute", "GovernanceGate", "Converge", "Settle"):
        assert phase in boot
    assert (root / "entities" / "index.md").is_file()
    assert (root / "LearningLayer" / "signals-2026-07-init.md").is_file()


def test_team_installed_and_loads() -> None:
    opts = _opts()
    run_init(opts)
    from weave.team.loader import load_manifest
    root = Path(opts.vault)
    from_templates = load_manifest()
    from_vault = load_manifest(Vault(root))
    assert {s.name for s in from_templates.seats} == {s.name for s in from_vault.seats}


# ---------- config wiring ----------

def test_desktop_config_wired() -> None:
    cfg_dir = _tmp_dir()
    desktop_path = cfg_dir / "desktop.json"
    desktop_path.write_text(json.dumps({
        "mcpServers": {"unrelated-server": {"command": "foo"}},
        "someOtherTopLevelKey": "keep-me",
    }))
    opts = _opts(claude_desktop_config=str(desktop_path))
    rc = run_init(opts)
    assert rc == 0

    cfg = json.loads(desktop_path.read_text())
    assert cfg["someOtherTopLevelKey"] == "keep-me"
    assert cfg["mcpServers"]["unrelated-server"] == {"command": "foo"}
    entry = cfg["mcpServers"]["weave-core"]
    assert entry["args"] == ["-m", "weave.mcp_server"]
    assert entry["env"]["WEAVE_VAULT_PATH"] == str(Path(opts.vault).expanduser().resolve())


def test_code_config_fallback_merge(monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError("real `claude` binary must never be invoked in tests")

    import weave.installer.config as cfgmod
    monkeypatch.setattr(cfgmod, "claude_binary_available", lambda: (_ for _ in ()).throw(AssertionError("shutil.which must not be called")))
    monkeypatch.setattr(cfgmod, "run_claude_mcp_add", _boom)

    cfg_dir = _tmp_dir()
    code_path = cfg_dir / "code.json"
    opts = _opts(claude_code_config=str(code_path))
    rc = run_init(opts)
    assert rc == 0

    cfg = json.loads(code_path.read_text())
    assert "weave-core" in cfg["mcpServers"]


# ---------- dry-run ----------

def test_dry_run_writes_nothing() -> None:
    vault_dir = _tmp_dir() / "vault"
    cfg_dir = _tmp_dir()
    desktop_path = cfg_dir / "desktop.json"
    code_path = cfg_dir / "code.json"
    opts = _opts(vault=str(vault_dir), claude_desktop_config=str(desktop_path),
                 claude_code_config=str(code_path), dry_run=True, yes=False)

    rc = run_init(opts)
    assert rc == 0
    assert not vault_dir.exists()
    assert not desktop_path.exists()
    assert not code_path.exists()


def test_dry_run_plan_lists_intended_actions() -> None:
    opts = _opts(dry_run=True, yes=False)
    plan = build_plan(opts)
    kinds = {a.kind for a in plan.actions}
    assert {"dir", "boot-file", "team", "mcp-config"} <= kinds
    assert plan.has_writes()


# ---------- consent ----------

def test_consent_decline_writes_nothing() -> None:
    vault_dir = _tmp_dir() / "vault"
    cfg_dir = _tmp_dir()
    desktop_path = cfg_dir / "desktop.json"
    code_path = cfg_dir / "code.json"
    opts = _opts(
        vault=str(vault_dir), claude_desktop_config=str(desktop_path),
        claude_code_config=str(code_path), yes=False,
        confirm_fn=lambda _plan_text: False,
    )

    rc = run_init(opts)
    assert rc == 0
    assert not vault_dir.exists()
    assert not desktop_path.exists()
    assert not code_path.exists()


def test_consent_accept_via_injected_confirm_writes() -> None:
    opts = _opts(yes=False, confirm_fn=lambda _plan_text: True)
    rc = run_init(opts)
    assert rc == 0
    assert Path(opts.vault).is_dir()


# ---------- idempotency ----------

def test_idempotent_rerun_skips() -> None:
    opts = _opts()
    run_init(opts)
    trash_dir = Path(opts.vault) / ".trash"
    assert not trash_dir.exists()

    plan = build_plan(opts)
    statuses = {a.status for a in plan.actions}
    assert statuses == {"skip-exists"}

    rc = run_init(opts)
    assert rc == 0
    assert not trash_dir.exists()


def test_force_rerun_tombstones() -> None:
    opts = _opts()
    run_init(opts)
    trash_dir = Path(opts.vault) / ".trash"
    assert not trash_dir.exists()

    opts_force = _opts(vault=opts.vault, claude_desktop_config=opts.claude_desktop_config,
                        claude_code_config=opts.claude_code_config, force=True)
    rc = run_init(opts_force)
    assert rc == 0
    assert trash_dir.is_dir()
    assert any(trash_dir.glob("*.md"))


# ---------- verify ----------

def test_verify_reports_green() -> None:
    opts = _opts()
    rc = run_init(opts)
    assert rc == 0

    doctor_report = run_doctor(opts.vault, include_mcp=False)
    assert doctor_report.failures() == 0

    team_report = validate_team(Vault(Path(opts.vault)))
    assert team_report.failures() == 0


# ---------- isolation from real machine state ----------

def test_config_override_isolates_real_files(monkeypatch) -> None:
    """Assert home-directory resolution is never consulted when overrides are set."""
    fence = _tmp_dir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fence))

    opts = _opts()
    rc = run_init(opts)
    assert rc == 0
    # Nothing should have been created under our fake "home".
    assert list(fence.iterdir()) == []


def test_target_none_skips_all_config() -> None:
    opts = _opts(target="none")
    plan = build_plan(opts)
    mcp_actions = [a for a in plan.actions if a.kind == "mcp-config"]
    assert len(mcp_actions) == 1
    assert mcp_actions[0].target == "(none detected)"

    rc = run_init(opts)
    assert rc == 0
    assert not Path(opts.claude_desktop_config).exists()
    assert not Path(opts.claude_code_config).exists()


# ---------- team self-repair (must_fix #1) ----------

def test_partial_team_install_self_repairs() -> None:
    """A missing team file (interrupted first run) must be restored on
    re-init, WITHOUT touching the other 12 files and WITHOUT tombstoning
    anything — and verify must go green afterwards.
    """
    opts = _opts()
    rc = run_init(opts)
    assert rc == 0

    root = Path(opts.vault)
    team_dir = root / opts.team_subdir
    team_files = sorted(team_dir.glob("*.md"))
    assert len(team_files) >= 2  # sanity: more than one template exists

    victim = team_files[0]
    victim_name = victim.name
    victim.unlink()
    assert not (team_dir / victim_name).exists()

    # Snapshot mtimes of the untouched survivors before re-running init.
    survivors = [p for p in team_files if p.name != victim_name]
    before_mtimes = {p.name: p.stat().st_mtime_ns for p in survivors}

    plan = build_plan(opts)
    team_action = next(a for a in plan.actions if a.kind == "team")
    assert team_action.status == "update"

    rc2 = run_init(opts)
    assert rc2 == 0

    # The missing file is restored.
    assert (team_dir / victim_name).is_file()

    # No tombstones were created — survivors were never routed through the
    # overwrite/tombstone path.
    trash_dir = root / ".trash"
    assert not trash_dir.exists()

    # Survivors are byte-for-byte untouched (mtime unchanged).
    for p in survivors:
        assert p.stat().st_mtime_ns == before_mtimes[p.name]

    # verify goes green.
    doctor_report = run_doctor(opts.vault, include_mcp=False)
    assert doctor_report.failures() == 0
    team_report = validate_team(Vault(root))
    assert team_report.failures() == 0


def test_partial_team_install_repair_message_not_already_present() -> None:
    """Regression: when the install is actually incomplete, init must NOT
    print the misleading 'already present — skipped' message.
    """
    opts = _opts()
    run_init(opts)
    root = Path(opts.vault)
    team_dir = root / opts.team_subdir
    victim = sorted(team_dir.glob("*.md"))[0]
    victim.unlink()

    messages: list[str] = []
    opts2 = _opts(vault=opts.vault, claude_desktop_config=opts.claude_desktop_config,
                  claude_code_config=opts.claude_code_config, echo_fn=messages.append)
    rc = run_init(opts2)
    assert rc == 0
    # The old bug: "team templates already present — skipped" printed even
    # though a file was actually missing. The plan render legitimately says
    # "N/13 team file(s) already present" (describing partial state), so we
    # check specifically for the misleading execution-time skip message.
    assert not any("already present — skipped" in m for m in messages)
    assert any("repaired" in m for m in messages)


# ---------- claude mcp add idempotency + scope (must_fix #2) ----------

def test_claude_mcp_add_called_once_with_scope_user(monkeypatch) -> None:
    """First init with the `claude` binary present and no config override:
    the injected runner is called exactly once, with --scope user.
    A second init (entry already present) must NOT call the runner again —
    the idempotency probe short-circuits it.
    """
    import weave.installer.config as cfgmod

    monkeypatch.setattr(cfgmod, "claude_binary_available", lambda: "/usr/bin/claude")

    calls: list[list[str]] = []

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_runner(args: list[str]):
        calls.append(args)
        return _FakeResult()

    cfg_dir = _tmp_dir()
    code_path = cfg_dir / "code.json"  # NOT passed as an override — simulates auto-detection
    # We still must not touch the real ~/.claude.json: force target detection
    # to treat "code" as wired without relying on Path.home(), by monkeypatching
    # default_code_config_path to our tempfile-backed path.
    monkeypatch.setattr(cfgmod, "default_code_config_path", lambda: code_path)

    opts = _opts(
        vault=str(_tmp_dir() / "vault"),
        claude_desktop_config=str(cfg_dir / "desktop.json"),
        claude_code_config=None,
        target="code",
        mcp_add_runner=_fake_runner,
    )
    rc = run_init(opts)
    assert rc == 0
    assert len(calls) == 1
    args = calls[0]
    assert args[0] == "/usr/bin/claude"
    assert args[1:4] == ["mcp", "add", "weave-core"]
    assert "--scope" in args
    assert args[args.index("--scope") + 1] == "user"

    # Second init: the weave-core entry now exists in code.json (written by
    # the JSON fallback the fake runner didn't actually perform — so seed it
    # directly to simulate what a real `claude mcp add` would have produced).
    import json as _json
    python_path = opts.python or __import__("sys").executable
    block = cfgmod.weave_core_mcp_block(python_path, str(Path(opts.vault).expanduser().resolve()))
    code_path.write_text(_json.dumps({"mcpServers": {"weave-core": block}}))

    rc2 = run_init(opts)
    assert rc2 == 0
    assert len(calls) == 1  # unchanged — probe short-circuited, runner not called again


def test_claude_mcp_add_skipped_when_override_supplied() -> None:
    """Sanity: when a --claude-code-config override IS supplied, the binary
    path must never be considered at all (existing contract, unchanged).
    """
    calls: list[list[str]] = []

    def _boom(args: list[str]):
        calls.append(args)
        raise AssertionError("runner must not be called when an override path is supplied")

    opts = _opts(mcp_add_runner=_boom)
    rc = run_init(opts)
    assert rc == 0
    assert calls == []


# ---------- generic templates: zero personal content ----------

def test_generic_templates_contain_no_personal_content() -> None:
    """grep the scaffolded output for banned terms -> zero.

    The default in-repo term is a synthetic canary that exercises the
    mechanism. Maintainers put their real private terms (project names,
    employer names, pseudonyms) one-per-line in tests/scrub_terms.local.txt
    — gitignored, so the terms themselves never land in the repo.

    Word-boundary matched so legitimate words do not false-positive on
    substrings (e.g. "synthesis" vs a banned term "thesis").
    """
    import re

    terms = ["weave-scrub-canary-term"]
    local_terms = Path(__file__).parent / "scrub_terms.local.txt"
    if local_terms.exists():
        terms += [line.strip() for line in
                  local_terms.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]

    opts = _opts()
    run_init(opts)
    root = Path(opts.vault)
    banned_patterns = [re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
                        for term in terms]
    hits: list[str] = []
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for pat in banned_patterns:
            if pat.search(text):
                hits.append(f"{path}: {pat.pattern}")
    assert hits == [], f"personal content leaked into generic scaffold: {hits}"
