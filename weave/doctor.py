"""Health check for The Weave 2.0 — `weave-cli doctor`.

Runs categorised checks against the engine, the vault, the environment, and
optionally the local Claude Desktop MCP wiring. Designed to catch the kinds
of silent failures real installs hit:

  - "All my smoke tests passed but Pattern 4 found 0 sessions"
    (the bug fixed in v0.1.1 — silent layout mismatch)
  - "Pattern 2 boot is empty"
    (the v1 graph-indexing bug, sanity-checked here so it stays dead)
  - "MCP server is wired but pointing at the wrong vault"
  - "Engine works but the human-side viewer is missing"

Exit code = number of failing checks (0 = all good). Warnings do not fail.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .vault import Vault, VaultPathError


# ---------- result types ----------

PASS = "pass"
WARN = "warn"
FAIL = "fail"
INFO = "info"
SKIP = "skip"

_ICONS = {PASS: "✓", WARN: "⚠", FAIL: "✗", INFO: "ℹ", SKIP: "–"}


@dataclass
class Check:
    name: str
    status: str
    message: str
    detail: str | None = None


@dataclass
class CheckGroup:
    name: str
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, message: str, detail: str | None = None) -> None:
        self.checks.append(Check(name, status, message, detail))


@dataclass
class DoctorReport:
    groups: list[CheckGroup]

    def failures(self) -> int:
        return sum(1 for g in self.groups for c in g.checks if c.status == FAIL)

    def warnings(self) -> int:
        return sum(1 for g in self.groups for c in g.checks if c.status == WARN)

    def to_text(self) -> str:
        lines: list[str] = ["🪶 Weave 2.0 Doctor", ""]
        for group in self.groups:
            lines.append(f"[{group.name}]")
            if not group.checks:
                lines.append(f"  {_ICONS[SKIP]} (no checks ran)")
            for c in group.checks:
                lines.append(f"  {_ICONS[c.status]} {c.message}")
                if c.detail:
                    for dline in c.detail.splitlines():
                        lines.append(f"      {dline}")
            lines.append("")
        f = self.failures()
        w = self.warnings()
        if f == 0 and w == 0:
            lines.append("All checks passed.")
        else:
            lines.append(f"{w} warning(s), {f} failure(s).")
        return "\n".join(lines)


# ---------- group: Engine ----------

REQUIRED_DEPS = ["mcp", "networkx", "frontmatter", "click", "pydantic", "numpy", "scipy"]


def check_engine() -> CheckGroup:
    g = CheckGroup("Engine")
    py = sys.version_info
    if py >= (3, 11):
        g.add("python", PASS, f"Python {platform.python_version()} (≥3.11 required)")
    else:
        g.add("python", FAIL, f"Python {platform.python_version()} — engine requires ≥3.11")

    missing: list[str] = []
    versions: list[str] = []
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    for dep in REQUIRED_DEPS:
        try:
            importlib.import_module(dep)
        except ImportError:
            missing.append(dep)
            continue
        try:
            # python-frontmatter installs under dist name "python-frontmatter"
            dist_name = "python-frontmatter" if dep == "frontmatter" else dep
            versions.append(f"{dep} {_pkg_version(dist_name)}")
        except PackageNotFoundError:
            versions.append(f"{dep} ?")
    if missing:
        g.add("deps", FAIL, f"Missing dependencies: {', '.join(missing)}",
              detail="Run: pip install -e .")
    else:
        g.add("deps", PASS, "Dependencies importable", detail=", ".join(versions))

    try:
        importlib.import_module("weave.cli")
        importlib.import_module("weave.mcp_server")
        g.add("entries", PASS, "CLI + MCP entry points importable")
    except ImportError as e:
        g.add("entries", FAIL, f"Entry point import failed: {e}")

    try:
        from importlib.metadata import version
        ver = version("theweave")
        g.add("version", INFO, f"theweave {ver}")
    except Exception:
        g.add("version", INFO, "theweave (version unknown — package not installed via pip?)")

    return g


# ---------- group: Vault ----------

def _detect_layout(vault: Vault) -> tuple[str, dict[str, list[str]]]:
    """Return ('flat' | 'canonical-nested' | 'mixed' | 'none', {sessions, entities, LearningLayer}).

    Each value is a list of rel paths where that directory appears. Real vaults
    sometimes have multiple (e.g. a canonical vault has both <Name>Vault/sessions/ and
    wiki/sessions/) — reporting all of them is more honest than first-match-wins.
    """
    found: dict[str, list[str]] = {"sessions": [], "entities": [], "LearningLayer": []}
    for path in vault.root.rglob("*"):
        if not path.is_dir():
            continue
        rel = path.relative_to(vault.root).as_posix()
        if any(p.startswith(".") for p in rel.split("/")):
            continue
        if path.name in found:
            found[path.name].append(rel)
    has_flat = "sessions" in found["sessions"] or "entities" in found["entities"]
    has_nested = any("/" in p for paths in found.values() for p in paths)
    if has_flat and has_nested:
        layout = "mixed"
    elif has_flat:
        layout = "flat"
    elif has_nested:
        layout = "canonical-nested"
    elif any(found.values()):
        layout = "flat"
    else:
        layout = "none"
    return layout, found


def check_vault(vault_path: str | None) -> CheckGroup:
    g = CheckGroup("Vault")
    if not vault_path:
        g.add("path", INFO, "No vault path set (skipping vault checks).",
              detail="Pass --vault or set WEAVE_VAULT_PATH to enable.")
        return g
    try:
        vault = Vault(vault_path)
    except VaultPathError as e:
        g.add("path", FAIL, f"Vault root invalid: {e}")
        return g
    g.add("path", PASS, f"Vault root resolves: {vault.root}")

    layout, found = _detect_layout(vault)
    detail_parts = [f"{k}/ → " + (", ".join(paths) if paths else "(none)")
                    for k, paths in found.items()]
    detail = "\n".join(detail_parts)
    if layout == "canonical-nested":
        g.add("layout", PASS, "Layout: canonical-nested", detail=detail)
    elif layout == "flat":
        g.add("layout", PASS, "Layout: flat (seed-vault style)", detail=detail)
    elif layout == "mixed":
        g.add("layout", WARN,
              "Layout: mixed — sessions/entities/LearningLayer dirs appear both at root AND nested",
              detail=detail + "\nPattern 4 will scan all of them; just confirm this is intentional.")
    else:
        g.add("layout", WARN, "Layout: no sessions/, entities/, or LearningLayer/ directory found",
              detail="Doctor will skip pattern-reachability checks. See README for canonical layout.")

    # Frontmatter sweep FIRST — broken YAML makes iter_notes() crash, so we walk
    # raw and catch parse errors before depending on parsed notes anywhere else.
    raw_errors: list[str] = []
    import frontmatter
    for path in vault.root.rglob("*.md"):
        if any(p.startswith(".") for p in path.relative_to(vault.root).parts):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                frontmatter.load(f)
        except Exception as e:
            raw_errors.append(f"{path.relative_to(vault.root)}: {type(e).__name__}")

    # Now iter_notes — skip files with broken frontmatter so the rest of the
    # doctor checks can still run.
    notes = []
    bad_paths = {e.split(":", 1)[0] for e in raw_errors}
    for path in vault.root.rglob("*.md"):
        if any(p.startswith(".") for p in path.relative_to(vault.root).parts):
            continue
        if str(path.relative_to(vault.root)) in bad_paths:
            continue
        try:
            notes.append(vault.load_note(vault.rel(path)))
        except Exception:
            pass
    by_kind = {"entities": 0, "sessions": 0, "signals": 0, "other": 0}
    bi_temporal_full = 0
    bi_temporal_total = 0
    for n in notes:
        rp = "/" + n.rel_path
        if "/entities/" in rp:
            by_kind["entities"] += 1
            bi_temporal_total += 1
            md = n.metadata
            if md.get("status") and md.get("valid_from") and "valid_until" in md:
                bi_temporal_full += 1
        elif "/sessions/" in rp:
            by_kind["sessions"] += 1
        elif "/LearningLayer/" in rp:
            by_kind["signals"] += 1
        else:
            by_kind["other"] += 1
    g.add("counts", PASS,
          f"{len(notes)} notes total — entities {by_kind['entities']}, "
          f"sessions {by_kind['sessions']}, signals {by_kind['signals']}, other {by_kind['other']}")

    if raw_errors:
        sample = "\n".join(raw_errors[:3])
        more = f"\n... and {len(raw_errors) - 3} more" if len(raw_errors) > 3 else ""
        g.add("frontmatter", WARN, f"{len(raw_errors)} frontmatter parse error(s)",
              detail=sample + more)
    else:
        g.add("frontmatter", PASS, "Frontmatter parses on all notes")

    # Pattern 4 reachability — use the consolidator's own logic, but on our
    # pre-filtered notes list so broken frontmatter elsewhere doesn't tank us.
    from datetime import date as _date, timedelta as _td
    from .pro.consolidator import Consolidator, _path_contains_dir
    cons = Consolidator(vault, window_days=3650)
    cutoff = _date.today() - _td(days=3650)
    p4_scannable = []
    for n in notes:
        if not _path_contains_dir(n.rel_path, "sessions"):
            continue
        d = cons._note_date(n)
        if d is not None and d >= cutoff:
            p4_scannable.append(n)
    # Detect notes that LOOK like sessions (explicit type: session OR filename
    # session-YYYY-MM-DD-...) but live outside any sessions/ dir. We deliberately
    # do NOT count every `date:`-bearing note, since briefs and signals also
    # carry dates and aren't sessions.
    def _is_session_shaped(n) -> bool:
        if n.metadata.get("type") == "session":
            return True
        import re as _re
        return bool(_re.match(r"session-\d{4}-\d{2}-\d{2}", n.name))
    missed = [n for n in notes
              if _is_session_shaped(n)
              and not _path_contains_dir(n.rel_path, "sessions")]
    if not p4_scannable and not missed:
        g.add("p4-reachability", INFO,
              "No session-shaped notes in vault yet (Pattern 4 would have nothing to consolidate)")
    elif missed:
        g.add("p4-reachability", WARN,
              f"Pattern 4 will scan {len(p4_scannable)} session(s); "
              f"{len(missed)} session-shaped note(s) live outside any sessions/ directory",
              detail="Examples (first 3): " + ", ".join(n.rel_path for n in missed[:3]))
    else:
        g.add("p4-reachability", PASS, f"Pattern 4 will scan {len(p4_scannable)} session(s)")

    # Pattern 2 graph — build directly on our pre-filtered notes list so broken
    # frontmatter elsewhere doesn't tank the graph build.
    try:
        import networkx as nx
        graph = nx.DiGraph()
        by_name = {n.name: n for n in notes}
        for n in notes:
            graph.add_node(n.name, type=n.metadata.get("type", "note"), path=n.rel_path)
        for n in notes:
            for target in n.wikilinks():
                if target in by_name:
                    graph.add_edge(n.name, target)
        nodes = graph.number_of_nodes()
        edges = graph.number_of_edges()
        isolates = sum(1 for n in graph.nodes if graph.degree(n) == 0)
        iso_pct = (100 * isolates / nodes) if nodes else 0
        if edges == 0 and nodes > 0:
            g.add("p2-graph", FAIL,
                  f"Pattern 2 graph: {nodes} nodes, 0 edges — wikilink indexing is BROKEN",
                  detail="This is the v1 regression. Check Note.wikilinks() and that vault notes contain [[wikilinks]].")
        elif iso_pct > 50 and nodes > 10:
            g.add("p2-graph", WARN,
                  f"Pattern 2 graph: {nodes} nodes, {edges} edges, {isolates} isolates ({iso_pct:.0f}%)",
                  detail="Over half of notes have no wikilinks — vault may be under-cross-referenced.")
        else:
            g.add("p2-graph", PASS,
                  f"Pattern 2 graph: {nodes} nodes, {edges} edges, {isolates} isolates ({iso_pct:.0f}%)")
    except Exception as e:
        g.add("p2-graph", FAIL, f"Pattern 2 graph build failed: {type(e).__name__}: {e}")

    # Batch-apply intent journal (consolidator crash safety): a pending
    # intent record older than a few minutes means an apply died mid-batch —
    # some targets patched, some not, with no error anywhere. Report which is
    # which (current file hash vs recorded pre/post hashes) and which backups
    # to restore. Doctor REPORTS; it never auto-restores.
    try:
        from .pro.intent_journal import intents_dir, stale_pending
        journal_dir = intents_dir(vault)
        stale = stale_pending(vault)
    except Exception as e:
        g.add("batch-apply", WARN,
              f"Intent journal location unresolvable: {type(e).__name__}: {e}",
              detail="Mid-batch crash detection is unavailable on this machine.")
        journal_dir = None
        stale = []

    def _record_detail(rec) -> list[str]:
        out = [f"intent {rec.intent_path.name} (created {rec.created_at}):"]
        for t in rec.targets:
            if t.state == "patched":
                out.append(f"  patched:   {t.rel_path}"
                           + (f" (backup: {t.backup_rel_path})" if t.backup_rel_path else ""))
            elif t.state == "unpatched":
                out.append(f"  UNPATCHED: {t.rel_path}")
            else:
                out.append(f"  {t.state}: {t.rel_path}"
                           + (f" (backup: {t.backup_rel_path})" if t.backup_rel_path else ""))
        return out

    # Split the stale records: every-target-patched means the apply FINISHED
    # but mark_completed failed (journal not finalized) — nothing to restore,
    # so WARN. FAIL is reserved for actual vault inconsistency (some targets
    # patched, some not) that needs operator action on vault files.
    partial = [r for r in stale if not r.all_patched()]
    unfinalized = [r for r in stale if r.all_patched()]

    if journal_dir is not None and journal_dir.exists() and not journal_dir.is_dir():
        # A broken journal location must never read as a green safety net —
        # stale_pending() legitimately finds nothing there.
        g.add("batch-apply", WARN,
              f"Intent journal location is not a directory: {journal_dir}",
              detail="Mid-batch crash detection cannot record or read intents "
                     "there. Remove or rename the blocking file.")
    elif partial:
        details: list[str] = []
        for rec in partial:
            details.extend(_record_detail(rec))
        details.append("To roll back, restore each patched target from its backup, "
                       "then delete or complete the intent record. Doctor never auto-restores.")
        g.add("batch-apply", FAIL,
              f"Partial batch apply detected — {len(partial)} pending intent record(s) "
              "from a consolidator run that died mid-batch",
              detail="\n".join(details))
    elif unfinalized:
        details = []
        for rec in unfinalized:
            details.extend(_record_detail(rec))
        details.append("Every target shows its recorded post-state — nothing to "
                       "restore. Delete the intent record(s) to clear this. "
                       "Doctor never auto-restores.")
        g.add("batch-apply", WARN,
              f"Batch apply completed but journal not finalized — "
              f"{len(unfinalized)} pending intent record(s) with all targets patched",
              detail="\n".join(details))
    else:
        g.add("batch-apply", PASS, "No stale batch-apply intents (no partial applies)")

    # Bi-temporal coverage
    if bi_temporal_total:
        pct = 100 * bi_temporal_full / bi_temporal_total
        msg = f"Bi-temporal coverage: {bi_temporal_full}/{bi_temporal_total} entities ({pct:.0f}%) with full status+valid_from+valid_until"
        if pct < 60:
            g.add("bi-temporal", WARN, msg,
                  detail="Add `status`, `valid_from`, `valid_until` to entity frontmatter.")
        else:
            g.add("bi-temporal", PASS, msg)
    else:
        g.add("bi-temporal", INFO, "No entities to check coverage on.")

    return g


# ---------- group: Environment ----------

def check_environment() -> CheckGroup:
    g = CheckGroup("Environment")

    obs = Path("/Applications/Obsidian.app")
    if obs.exists():
        g.add("obsidian", PASS, "Obsidian.app detected in /Applications/")
    else:
        g.add("obsidian", INFO,
              "Obsidian.app not detected — recommended for human-side vault navigation",
              detail="The engine works against any markdown directory; Obsidian is not required.\n"
                     "Install from https://obsidian.md/ for backlink-aware browsing.")

    if os.environ.get("ANTHROPIC_API_KEY"):
        g.add("anthropic-key", PASS, "ANTHROPIC_API_KEY set — Pattern 4/5 live mode available")
    else:
        g.add("anthropic-key", INFO,
              "ANTHROPIC_API_KEY not set — Pattern 4/5 will run in mock mode",
              detail="Export ANTHROPIC_API_KEY to enable live reflect + semantic merge.")

    return g


# ---------- group: MCP (optional) ----------

def _claude_config_path() -> Path:
    return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"


def check_mcp() -> CheckGroup:
    g = CheckGroup("MCP")
    cfg_path = _claude_config_path()
    if not cfg_path.exists():
        g.add("config", WARN, f"Claude Desktop config not found at {cfg_path}",
              detail="If you don't run Claude Desktop on this machine, ignore this group.")
        return g
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception as e:
        g.add("config", FAIL, f"Config exists but is not valid JSON: {e}")
        return g
    g.add("config", PASS, f"Config found: {cfg_path}")

    servers = cfg.get("mcpServers", {})
    entry = servers.get("weave-core")
    if not entry:
        g.add("weave-core", FAIL,
              "`weave-core` not in mcpServers",
              detail="Add the weave-core block to claude_desktop_config.json — see README.")
        return g
    g.add("weave-core", PASS, "`weave-core` registered in mcpServers")

    cmd = entry.get("command", "")
    if cmd and Path(cmd).exists():
        g.add("python-binary", PASS, f"command path resolves: {cmd}")
    else:
        g.add("python-binary", FAIL, f"command path does not exist: {cmd!r}")

    env_path = (entry.get("env") or {}).get("WEAVE_VAULT_PATH")
    if not env_path:
        g.add("vault-env", WARN, "WEAVE_VAULT_PATH not set in MCP env block",
              detail="weave-core will fail at startup without this.")
    elif not Path(env_path).expanduser().is_dir():
        g.add("vault-env", FAIL,
              f"WEAVE_VAULT_PATH in MCP env block does not exist: {env_path}")
    else:
        g.add("vault-env", PASS, f"WEAVE_VAULT_PATH resolves: {env_path}")

    return g


# ---------- top-level ----------

def run_doctor(vault_path: str | None, include_mcp: bool) -> DoctorReport:
    groups = [check_engine(), check_vault(vault_path), check_environment()]
    if include_mcp:
        groups.append(check_mcp())
    return DoctorReport(groups=groups)
