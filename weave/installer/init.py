"""weave-cli init — the one-click installer orchestrator.

`run_init(opts) -> int` is the non-interactive entry point the test suite
calls directly. It builds an inspectable `InstallPlan` (list of `Action`s)
BEFORE writing anything, prints/renders that plan for consent, then
executes only if allowed to.

Phases: PLAN -> CONSENT -> EXECUTE -> VERIFY. See module docstrings in
scaffold.py / config.py for the pieces being orchestrated.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Callable

from ..doctor import run_doctor
from ..team.installer import install_team, repair_team
from ..team.loader import TEMPLATES_DIR as TEAM_TEMPLATES_DIR
from ..team.validator import validate_team
from ..vault import Vault
from . import config as cfgmod
from .scaffold import apply_scaffold, scaffold_status


# ---------- options ----------

@dataclass
class InstallOptions:
    vault: str
    target: str = "auto"                    # auto|desktop|code|both|none
    claude_desktop_config: str | None = None  # override path (test seam)
    claude_code_config: str | None = None     # override path (test seam)
    python: str | None = None                 # defaults to sys.executable
    yes: bool = False
    dry_run: bool = False
    force: bool = False
    team_subdir: str = "entities"
    today: _date | None = None                # override 'today' for deterministic tests
    # Test/automation hooks — never used by the real CLI path:
    confirm_fn: Callable[[str], bool] | None = None   # injected decline/accept, bypasses stdin
    echo_fn: Callable[[str], None] | None = None       # injected output sink
    mcp_add_runner: Callable[[list[str]], object] | None = None  # injected fake for `claude mcp add` shell-out


# ---------- plan ----------

@dataclass
class Action:
    kind: str            # "dir" | "boot-file" | "team" | "mcp-config"
    target: str           # human-readable path/key
    status: str           # "create" | "skip-exists" | "update" | "conflict"
    detail: str = ""
    apply: Callable[[], None] | None = field(default=None, repr=False)


@dataclass
class InstallPlan:
    vault_root: Path
    actions: list[Action] = field(default_factory=list)

    def add(self, action: Action) -> None:
        self.actions.append(action)

    def render(self) -> str:
        lines = [f"Plan for vault: {self.vault_root}", ""]
        for a in self.actions:
            lines.append(f"  [{a.status:11}] {a.kind:10} {a.target}")
            if a.detail:
                lines.append(f"               {a.detail}")
        lines.append("")
        lines.append(
            "This will create files under the vault above, and may modify the "
            "weave-core entry in the Claude config(s) listed."
        )
        return "\n".join(lines)

    def has_writes(self) -> bool:
        return any(a.status in ("create", "update") for a in self.actions)


# ---------- plan builders ----------

def _plan_scaffold(plan: InstallPlan, vault_root: Path, today: _date | None) -> None:
    status = scaffold_status(vault_root, today)
    for rel, st in status.items():
        kind = "dir" if rel.endswith("/") else "boot-file"
        plan.add(Action(kind=kind, target=rel, status=st))


def _plan_team(plan: InstallPlan, vault_root: Path, subdir: str) -> None:
    existing = []
    for path in sorted(TEAM_TEMPLATES_DIR.rglob("*.md")):
        dest_rel = f"{subdir}/{path.name}" if subdir else path.name
        if (vault_root / dest_rel).exists():
            existing.append(dest_rel)
    n_total = len(list(TEAM_TEMPLATES_DIR.rglob("*.md")))
    if not existing:
        plan.add(Action(kind="team", target=f"{subdir or '.'}/ ({n_total} files)", status="create"))
    elif len(existing) == n_total:
        plan.add(Action(kind="team", target=f"{subdir or '.'}/ ({n_total} files)", status="skip-exists"))
    else:
        plan.add(Action(
            kind="team", target=f"{subdir or '.'}/ ({n_total} files)", status="update",
            detail=f"{len(existing)}/{n_total} team file(s) already present",
        ))


def _plan_mcp(plan: InstallPlan, kind_label: str, cfg_path: Path, desired_block: dict) -> str:
    """Add an mcp-config Action for one config file. Returns the resolved status."""
    existing_cfg = cfgmod.load_json_config(cfg_path) if cfg_path.exists() else {}
    existing_entry = (existing_cfg.get("mcpServers") or {}).get("weave-core")
    status = cfgmod.diff_mcp_entry(existing_entry, desired_block)
    detail = f"{cfg_path}"
    if status == "update":
        detail += f" (existing: {existing_entry})"
    plan.add(Action(kind="mcp-config", target=f"{kind_label}: weave-core", status=status, detail=detail))
    return status


# ---------- target detection ----------

def _detect_targets(opts: InstallOptions) -> tuple[Path | None, Path | None]:
    """Resolve which config path(s) to wire, honoring overrides + --target.

    Returns (desktop_path_or_None, code_path_or_None). A path is returned
    only if that target should be wired at all (detected or forced).
    Detection/writes use ONLY resolved paths — Path.home() is called only
    inside the default_*_config_path() helpers, and only when no override
    was supplied.
    """
    desktop_override = Path(opts.claude_desktop_config).expanduser() if opts.claude_desktop_config else None
    code_override = Path(opts.claude_code_config).expanduser() if opts.claude_code_config else None

    desktop_path = desktop_override or cfgmod.default_desktop_config_path()
    code_path = code_override or cfgmod.default_code_config_path()

    if opts.target == "none":
        return None, None
    if opts.target == "desktop":
        return desktop_path, None
    if opts.target == "code":
        return None, code_path
    if opts.target == "both":
        return desktop_path, code_path

    # auto: wire whatever is detected. An explicit override counts as
    # "wire this one" even if the file doesn't exist yet (the user told us
    # exactly where to write).
    wire_desktop = bool(desktop_override) or desktop_path.exists()
    wire_code = bool(code_override) or code_path.exists() or (
        code_override is None and cfgmod.claude_binary_available() is not None
    )
    return (desktop_path if wire_desktop else None), (code_path if wire_code else None)


# ---------- build plan ----------

def build_plan(opts: InstallOptions) -> InstallPlan:
    vault_root = Path(opts.vault).expanduser().resolve()
    plan = InstallPlan(vault_root=vault_root)

    plan.add(Action(kind="dir", target=str(vault_root), status="create" if not vault_root.is_dir() else "skip-exists"))

    if vault_root.is_dir():
        _plan_scaffold(plan, vault_root, opts.today)
        _plan_team(plan, vault_root, opts.team_subdir)
    else:
        # Vault dir doesn't exist yet — everything under it is necessarily "create".
        for rel in ("entities/", "LearningLayer/", "sessions/"):
            plan.add(Action(kind="dir", target=rel, status="create"))
        plan.add(Action(kind="boot-file", target="BOOT.md", status="create"))
        plan.add(Action(kind="boot-file", target="entities/index.md", status="create"))
        plan.add(Action(kind="boot-file", target="LearningLayer/signals-<init>.md", status="create"))
        n_total = len(list(TEAM_TEMPLATES_DIR.rglob("*.md")))
        plan.add(Action(kind="team", target=f"{opts.team_subdir or '.'}/ ({n_total} files)", status="create"))

    python_path = opts.python or sys.executable
    desktop_path, code_path = _detect_targets(opts)
    block = cfgmod.weave_core_mcp_block(python_path, str(vault_root))

    if desktop_path is not None:
        _plan_mcp(plan, "Claude Desktop", desktop_path, block)
    if code_path is not None:
        _plan_mcp(plan, "Claude Code", code_path, block)
    if desktop_path is None and code_path is None:
        plan.add(Action(kind="mcp-config", target="(none detected)", status="skip-exists",
                         detail="No Claude config detected/selected; vault scaffold still proceeds."))

    return plan


# ---------- execute ----------

def _execute(opts: InstallOptions, plan: InstallPlan, echo: Callable[[str], None]) -> None:
    vault_root = plan.vault_root
    vault_root.mkdir(parents=True, exist_ok=True)
    vault = Vault(vault_root)

    # Scaffold (dirs + boot files)
    written = apply_scaffold(vault, force=opts.force, today=opts.today)
    if written:
        echo(f"scaffolded: {', '.join(written)}")

    # Team install
    team_action = next((a for a in plan.actions if a.kind == "team"), None)
    if team_action and team_action.status in ("create", "update"):
        if team_action.status == "update" and not opts.force:
            # Partial/interrupted prior install: self-repair by writing ONLY
            # the missing template files. Never tombstones or touches files
            # that are already present — no FileExistsError to swallow.
            written = repair_team(vault, subdir=opts.team_subdir)
            if written:
                echo(f"team repaired ({len(written)} missing file(s) restored) into {opts.team_subdir or '.'}/")
            else:
                echo("team templates already present — skipped (pass --force to overwrite)")
        else:
            # Fresh install (status == "create"), or an explicit --force
            # tombstone-and-replace-all of a fully/partially existing set.
            install_team(vault, subdir=opts.team_subdir, force=opts.force)
            echo(f"team installed into {opts.team_subdir or '.'}/")

    # Config wiring
    python_path = opts.python or sys.executable
    desktop_path, code_path = _detect_targets(opts)
    block = cfgmod.weave_core_mcp_block(python_path, str(vault_root))

    if desktop_path is not None:
        cfg = cfgmod.load_json_config(desktop_path)
        entry = (cfg.get("mcpServers") or {}).get("weave-core")
        if cfgmod.diff_mcp_entry(entry, block) != "skip-exists":
            new_cfg = cfgmod.merge_mcp_server(cfg, "weave-core", block)
            cfgmod.atomic_write_text(desktop_path, __import__("json").dumps(new_cfg, indent=2) + "\n")
            echo(f"wrote Claude Desktop config: {desktop_path}")

    if code_path is not None:
        # Prefer `claude mcp add` ONLY when no override was supplied, the
        # binary is on PATH, AND the idempotency probe shows no equivalent
        # weave-core entry already exists — tests always supply an override
        # OR an injected mcp_add_runner, so the real subprocess path is
        # never exercised under test.
        existing_cfg = cfgmod.load_json_config(code_path)
        existing_entry = (existing_cfg.get("mcpServers") or {}).get("weave-core")
        probe_status = cfgmod.diff_mcp_entry(existing_entry, block)

        no_override = opts.claude_code_config is None
        binary_candidate = no_override and cfgmod.claude_binary_available() is not None
        use_binary = binary_candidate and probe_status != "skip-exists"
        if use_binary:
            claude_bin = cfgmod.claude_binary_available()
            add_kwargs = {"runner": opts.mcp_add_runner} if opts.mcp_add_runner is not None else {}
            result = cfgmod.run_claude_mcp_add(claude_bin, str(vault_root), python_path, **add_kwargs)
            if result.returncode == 0:
                echo(f"registered weave-core via `claude mcp add`")
            else:
                echo(f"`claude mcp add` failed (rc={result.returncode}); falling back to JSON merge")
                use_binary = False
        elif binary_candidate and probe_status == "skip-exists":
            echo("weave-core entry already present in Claude Code config — skipping `claude mcp add`")
        if not use_binary:
            cfg = cfgmod.load_json_config(code_path)
            entry = (cfg.get("mcpServers") or {}).get("weave-core")
            if cfgmod.diff_mcp_entry(entry, block) != "skip-exists":
                new_cfg = cfgmod.merge_mcp_server(cfg, "weave-core", block)
                cfgmod.atomic_write_text(code_path, __import__("json").dumps(new_cfg, indent=2) + "\n")
                echo(f"wrote Claude Code config: {code_path}")


# ---------- verify ----------

def _verify(opts: InstallOptions, plan: InstallPlan, echo: Callable[[str], None]) -> int:
    desktop_path, _code_path = _detect_targets(opts)
    include_mcp = desktop_path is not None
    doctor_report = run_doctor(str(plan.vault_root), include_mcp=False)
    echo(doctor_report.to_text())

    team_report = validate_team(Vault(plan.vault_root))
    echo(team_report.to_text())

    return doctor_report.failures() + team_report.failures()


# ---------- top-level ----------

def run_init(opts: InstallOptions) -> int:
    echo = opts.echo_fn or (lambda s: print(s))
    plan = build_plan(opts)

    if opts.dry_run:
        echo(plan.render())
        echo("(dry-run — nothing written)")
        return 0

    echo(plan.render())

    if not opts.yes:
        confirm = opts.confirm_fn
        if confirm is None:
            import click
            confirmed = click.confirm(
                "Proceed? This will create the above and modify the listed Claude config(s)."
            )
        else:
            confirmed = confirm(plan.render())
        if not confirmed:
            echo("Declined — nothing written.")
            return 0

    _execute(opts, plan, echo)
    return _verify(opts, plan, echo)


__all__ = ["InstallOptions", "InstallPlan", "Action", "build_plan", "run_init"]
