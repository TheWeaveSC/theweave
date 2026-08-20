"""Weave 2.0 sandbox CLI — `weave demo …` entry-point.

All commands operate against a vault directory chosen via:
  1. --vault flag, OR
  2. WEAVE_VAULT_PATH env var, OR
  3. default `./seed-vault` relative to the sandbox root.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

import click

from .vault import Vault
from .core import WeaveCore


# ---------- shared option ----------

def _resolve_vault(vault_opt: str | None) -> Vault:
    candidates = [
        vault_opt,
        os.environ.get("WEAVE_VAULT_PATH"),
        str((Path(__file__).parent.parent / "seed-vault").resolve()),
    ]
    for c in candidates:
        if c and Path(c).expanduser().is_dir():
            return Vault(c)
    click.echo("ERROR: could not resolve vault path; pass --vault or set WEAVE_VAULT_PATH.", err=True)
    sys.exit(2)


vault_option = click.option(
    "--vault", "-V", default=None,
    help="Path to the vault. Defaults to ./seed-vault, or $WEAVE_VAULT_PATH.",
)


def _resolve_vault_strict(vault_opt: str | None) -> Vault:
    """No seed-vault fallback. Cortex commands (esp. the unattended nightly
    dream, which WRITES a brief) must never silently retarget the demo
    fixture because an env var was evicted or typo'd."""
    for c in (vault_opt, os.environ.get("WEAVE_VAULT_PATH")):
        if c:
            if Path(c).expanduser().is_dir():
                return Vault(c)
            click.echo(f"ERROR: vault path does not exist: {c}", err=True)
            sys.exit(2)
    click.echo("ERROR: cortex commands need an explicit vault — pass --vault "
               "or set WEAVE_VAULT_PATH (no seed-vault fallback).", err=True)
    sys.exit(2)


# ---------- root group ----------

@click.group()
def cli() -> None:
    """The Weave 2.0 sandbox — five-pattern memory architecture demo."""


# ---------- info ----------

@cli.command()
@vault_option
def info(vault: str | None) -> None:
    """Print sandbox status — which patterns are wired, LLM mode, vault stats."""
    v = _resolve_vault(vault)
    notes = list(v.iter_notes())
    by_dir: dict[str, int] = {}
    root_files: list[str] = []
    for n in notes:
        parts = n.rel_path.split("/", 1)
        if len(parts) == 2:
            by_dir[parts[0]] = by_dir.get(parts[0], 0) + 1
        else:
            root_files.append(parts[0])

    from .pro.llm import is_mock
    mode = "MOCK (offline — set ANTHROPIC_API_KEY to switch)" if is_mock() else "Claude (live API)"

    click.echo("🪶 Weave 2.0 — sandbox")
    click.echo(f"  vault: {v.root}")
    summary = f"{len(by_dir)} folder(s)"
    if root_files:
        summary += f" + {len(root_files)} root file(s)"
    click.echo(f"  notes: {len(notes)} across {summary}")
    for k, n in sorted(by_dir.items()):
        click.echo(f"    {k}/: {n}")
    for fname in sorted(root_files):
        click.echo(f"    {fname}")
    click.echo("")
    click.echo("Pattern wiring:")
    click.echo("  1. Weave Core 5-verb MCP   ✅ (run `weave mcp` or `python -m weave.mcp_server`)")
    click.echo("  2. PPR boot retriever       ✅ (`weave demo boot <query>`)")
    click.echo("  3. Bi-temporal resolver     ✅ (`weave demo current <name>`)")
    click.echo("  4. Sleep-time consolidator  ✅ (`weave demo consolidate [--apply]`)")
    click.echo("  5. Write-time conflict      ✅ (`weave demo write <file>`)")
    click.echo("")
    click.echo(f"LLM mode: {mode}")


# ---------- doctor ----------

@cli.command()
@click.option("--vault", "-V", default=None,
              help="Path to the vault. Defaults to $WEAVE_VAULT_PATH; if neither is set, vault checks are skipped.")
@click.option("--check-mcp/--no-check-mcp", default=False,
              help="Also check the local Claude Desktop MCP wiring.")
def doctor(vault: str | None, check_mcp: bool) -> None:
    """Health check — engine, vault, environment, optional MCP wiring.

    Exit code = number of failures (0 = all good). Warnings do not fail.
    """
    from .doctor import run_doctor
    vault_path = vault or os.environ.get("WEAVE_VAULT_PATH")
    report = run_doctor(vault_path, include_mcp=check_mcp)
    click.echo(report.to_text())
    sys.exit(report.failures())


# ---------- lint ----------

_YAML_LINE_RE = re.compile(r"line (\d+), column (\d+)")


def _fault_hint(v, fault) -> list[str]:
    """Show the offending line, and name the defect when we recognise it.

    "your YAML is broken" costs a hunt through 600 files. "line 3 — quote the
    value" costs ten seconds. The 13 Aug outage was exactly this defect and it
    ran for two days.
    """
    m = _YAML_LINE_RE.search(fault.error)
    if not m:
        return []
    lineno = int(m.group(1))
    try:
        lines = v.read_text(fault.rel_path).splitlines()
    except Exception:
        return []
    if not (1 <= lineno <= len(lines)):
        return []
    out = [f"  {lineno}: {lines[lineno - 1]}"]
    if "mapping values are not allowed" in fault.error:
        out.append("  ^ an unquoted value containing ': ' — YAML reads it as a "
                   "nested key. Wrap the value in single quotes.")
    return out


@cli.command("lint")
@vault_option
@click.option("--paths", is_flag=True, default=False,
              help="Print only the faulting rel_paths, one per line (for scripts/hooks).")
def lint_cmd(vault: str | None, paths: bool) -> None:
    """Validate every note's frontmatter. Exit code = number of faults.

    v0.5 item 17. Run this at session end, not at 03:30. A malformed note is
    invisible to the cortex — never indexed, never graphed, never retrievable —
    and until item 16 lands it also aborts the nightly rebuild outright. The
    cheapest place to catch a bad edit is right after making it.
    """
    v = _resolve_vault_strict(vault)
    notes, faults = v.iter_notes_safe()

    if paths:
        for f in faults:
            click.echo(f.rel_path)
        sys.exit(len(faults))

    if not faults:
        click.echo(f"vault lint: {len(notes)} notes, 0 faults.")
        sys.exit(0)

    click.echo(f"vault lint: {len(notes)} parsed, {len(faults)} FAULT(S)\n")
    for f in faults:
        click.echo(f"✗ {f.rel_path}")
        click.echo(f"    {f.kind}: {f.error}")
        for line in _fault_hint(v, f):
            click.echo(f"  {line}")
        click.echo("")
    click.echo(f"{len(faults)} fault(s). These notes are NOT in the cortex — "
               "not indexed, not graphed, not retrievable — until fixed.")
    sys.exit(len(faults))


# ---------- demo group ----------

@cli.group()
def demo() -> None:
    """Run the demo paths for each pattern."""


# ---------- demo boot ----------

@demo.command("boot")
@click.argument("query", nargs=-1, required=True)
@click.option("--top", default=8, show_default=True, help="Top-N notes to return.")
@click.option("--excerpts/--no-excerpts", default=True, help="Include note excerpts.")
@vault_option
def demo_boot(query: tuple[str, ...], top: int, excerpts: bool, vault: str | None) -> None:
    """Boot retrieval — cortex hybrid recall when built, PPR otherwise (loud)."""
    v = _resolve_vault(vault)
    q = " ".join(query)

    from .pro.cortex import cortex_exists
    if cortex_exists(v):
        from .pro.recall import recall
        # Boot orients on CURRENT state: superseded versions stay out (the
        # recall verb still reaches them for explicit history queries).
        r = recall(v, q, k=top, include_superseded=False)
        click.echo(r.to_text())
        if excerpts and not r.degraded:
            from .pro.ppr import _excerpt
            click.echo("")
            for h in r.hits:
                try:
                    body = v.load_note(h.rel_path).content
                except Exception:
                    continue
                click.echo(f"  {h.note_name}: {_excerpt(body, 220)}")
        return

    from .pro.ppr import PPRBoot
    click.echo("⚠ cortex absent — boot degrades to PPR-only (reduced recall); "
               "run `weave cortex rebuild` to enable hybrid recall.")
    ppr = PPRBoot(v)
    ppr.build()
    res = ppr.run(q, top_n=top)
    click.echo(ppr.format_boot(res, include_excerpts=excerpts))


# ---------- demo current ----------

@demo.command("current")
@click.argument("name")
@click.option("--as-of", default=None, help="Resolve as-of an ISO date (YYYY-MM-DD).")
@vault_option
def demo_current(name: str, as_of: str | None, vault: str | None) -> None:
    """Pattern 3 — walk the bi-temporal supersession chain to the current version."""
    from .pro.bitemporal import BiTemporalResolver
    v = _resolve_vault(vault)
    r = BiTemporalResolver(v)
    as_of_date = date.fromisoformat(as_of) if as_of else None
    res = r.resolve(name, as_of=as_of_date)
    click.echo(f"query:   {res.query}")
    click.echo(f"chain:   {' → '.join(res.chain)}")
    if res.current is None:
        click.echo("current: (not found)")
        return
    click.echo(f"current: {res.current.name}")
    click.echo(f"path:    {res.current.rel_path}")
    click.echo(f"version: {res.current.metadata.get('version', '(unversioned)')}")
    click.echo(f"valid_from: {res.current.metadata.get('valid_from', '?')}")
    click.echo(f"valid_until: {res.current.metadata.get('valid_until', 'currently valid')}")
    if res.hopped:
        click.echo(f"\n(hopped {len(res.chain)-1}× from queried name)")


# ---------- demo write ----------

@demo.command("write")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", default=None, help="Override the note name (default: file stem).")
@vault_option
def demo_write(source_file: str, name: str | None, vault: str | None) -> None:
    """Pattern 5 — propose ADD/UPDATE/DELETE/NOOP for a candidate new note."""
    from .pro.conflict import ConflictResolver
    v = _resolve_vault(vault)
    src = Path(source_file)
    content = src.read_text(encoding="utf-8")
    note_name = name or src.stem
    r = ConflictResolver(v)
    p = r.propose(new_note_name=note_name, new_note_content=content)
    click.echo(f"🧠 Write-time conflict resolution for `{note_name}`")
    click.echo(f"  verdict: {click.style(p.verdict, bold=True)}")
    click.echo(f"  target:  {p.target_path or '(n/a)'}")
    click.echo(f"  is_mock: {p.is_mock}")
    click.echo(f"  rationale: {p.rationale}")
    click.echo()
    click.echo("  top similarity candidates:")
    for path, score in p.candidates:
        click.echo(f"    {score:.3f}  {path}")


# ---------- demo consolidate ----------

@demo.command("consolidate")
@click.option("--window-days", default=120, show_default=True, help="Lookback window in days.")
@click.option("--apply", "apply_changes", is_flag=True, default=False,
              help="Apply patches to entity files (with _archive/ backup). Default is dry-run.")
@click.option("--today", default=None, help="Override 'today' for deterministic demos (YYYY-MM-DD).")
@vault_option
def demo_consolidate(window_days: int, apply_changes: bool, today: str | None, vault: str | None) -> None:
    """Pattern 4 — sleep-time consolidation pass over recent sessions + LearningLayer."""
    from .pro.consolidator import Consolidator
    v = _resolve_vault(vault)
    today_date = date.fromisoformat(today) if today else date.today()
    c = Consolidator(v, window_days=window_days)
    report = c.build_report(today=today_date)

    if apply_changes:
        patched = c.apply(report)
        click.echo(report.to_markdown())
        click.echo("\n--- APPLIED ---")
        for p in patched:
            click.echo(f"  patched: {p}")
        click.echo(f"  backups in: _archive/")
    else:
        rel = c.write_report_only(report)
        click.echo(report.to_markdown())
        click.echo(f"\n(dry-run — no entity files patched; report saved to `{rel}`)")
        click.echo(f"Re-run with --apply to patch entities.")


# ---------- demo write-fixture (helper to seed a tester file) ----------

@demo.command("write-fixture")
@click.option("--out", default="/tmp/weave-fixture-new-session.md")
def demo_fixture(out: str) -> None:
    """Write a sample new-session file to /tmp for use with `weave demo write`."""
    Path(out).write_text(
        "---\n"
        "date: 2026-05-23\n"
        "type: session\n"
        'touches: ["[[entity-ACME-v1.2.8]]", "[[entity-Marcus]]"]\n'
        "---\n\n"
        "# ACME Dry-Run Green\n\n"
        "Re-tested replication after WAL tuning. Lag well under threshold.\n"
        "Marcus approved. Migration window confirmed for 2026-06-01.\n",
        encoding="utf-8",
    )
    click.echo(f"wrote sample new session to: {out}")
    click.echo(f"now try:  weave demo write {out}")


# ---------- recall (hybrid read path, W2) ----------

@cli.command("recall")
@click.argument("query", nargs=-1, required=True)
@click.option("--top", "-k", default=8, show_default=True)
@click.option("--lane", default="operational", show_default=True,
              type=click.Choice(["operational", "thesis", "neutral"]),
              help="lane firewall lane to search. Only notes in the chosen "
                   "lane (or neutral) are retrievable — pick deliberately, "
                   "never auto-detected.")
@click.option("--fake-embedder", is_flag=True, default=False, hidden=True)
@vault_option
def recall_cmd(query: tuple[str, ...], top: int, lane: str, fake_embedder: bool,
               vault: str | None) -> None:
    """Hybrid semantic recall (dense + graph PPR). Degrades loudly without cortex."""
    from .pro.recall import recall
    emb = None
    if fake_embedder:
        from .pro.embedder import FakeEmbedder
        emb = FakeEmbedder()
    result = recall(_resolve_vault_strict(vault), " ".join(query), k=top,
                     embedder=emb, lane=lane)
    click.echo(result.to_text())


# ---------- cortex (derived acceleration layer, W1+) ----------

@cli.group()
def cortex() -> None:
    """The Weave Cortex — derived, rebuildable acceleration layer (cache semantics)."""


@cortex.command("rebuild")
@click.option("--fake-embedder", is_flag=True, default=False, hidden=True,
              help="Offline deterministic embedder (tests/CI only).")
@click.option("--allow-unruled-bridges", is_flag=True, default=False,
              help="Proceed (with loud warnings) even if the bridge detector "
                   "finds files with no lane_map ruling. Default: fail closed.")
@vault_option
def cortex_rebuild(fake_embedder: bool, allow_unruled_bridges: bool,
                   vault: str | None) -> None:
    """Rebuild the whole cortex from markdown (I1: derived, deletable)."""
    from .pro.cortex import BridgeFilesUnruled, rebuild
    v = _resolve_vault_strict(vault)
    emb = None
    if fake_embedder:
        from .pro.embedder import FakeEmbedder
        emb = FakeEmbedder()
    try:
        st = rebuild(v, embedder=emb, log=click.echo,
                     allow_unruled_bridges=allow_unruled_bridges)
    except BridgeFilesUnruled as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(st.to_text())


@cortex.command("status")
@vault_option
def cortex_status(vault: str | None) -> None:
    """Show cortex freshness (manifest vs current vault content)."""
    from .pro.cortex import status
    click.echo(status(_resolve_vault_strict(vault)).to_text())


@cortex.command("clear")
@click.option("--all", "everything", is_flag=True, default=False,
              help="Also delete bookkeeping.db (telemetry history).")
@vault_option
def cortex_clear(everything: bool, vault: str | None) -> None:
    """Delete the derived cortex artifacts. Loses speed, never memory (I1).
    Telemetry history survives unless --all is given."""
    from .pro.cortex import clear
    out = clear(_resolve_vault_strict(vault), everything=everything)
    click.echo(f"cleared {out}" + ("" if everything else " (bookkeeping.db kept)"))


@cortex.command("stats")
@vault_option
def cortex_stats(vault: str | None) -> None:
    """Bookkeeping stats: logged retrievals, tracked notes, co-occurrence pairs."""
    from .pro.cortex import cortex_dir
    from .pro.bookkeeping import stats
    s = stats(cortex_dir(_resolve_vault_strict(vault)))
    for k_, v_ in s.items():
        click.echo(f"{k_}: {v_}")


@cortex.command("propose")
@click.option("--today", default=None, help="Override 'today' (YYYY-MM-DD, tests).")
@vault_option
def cortex_propose(today: str | None, vault: str | None) -> None:
    """Emit a proposal report (wikilinks / staleness / salience). I5: writes
    ONLY inside the cortex; apply accepted items via the normal write path."""
    from datetime import date as _date
    from .pro.bookkeeping import propose
    t = _date.fromisoformat(today) if today else None
    out = propose(_resolve_vault_strict(vault), today=t)
    click.echo(f"proposal written: {out}")
    click.echo(out.read_text(encoding="utf-8"))


@cortex.command("dream")
@click.option("--date", "day_str", default=None, help="Brief date (YYYY-MM-DD; default today).")
@click.option("--brief-dir", default=None, help="Vault-relative briefs dir (default: auto-detect).")
@click.option("--dry-run", is_flag=True, default=False, help="Print, don't write the vault.")
@vault_option
def cortex_dream(day_str: str | None, brief_dir: str | None, dry_run: bool,
                 vault: str | None) -> None:
    """Sleep-time job: write the anticipatory morning brief (the one
    sanctioned vault write), then delete the cortex scratch."""
    from datetime import date as _date
    from .pro.dreamer import dream, DreamError
    v = _resolve_vault_strict(vault)
    day = _date.fromisoformat(day_str) if day_str else None
    try:
        res = dream(v, day=day, brief_dir=brief_dir, dry_run=dry_run)
    except DreamError as e:
        click.echo(f"DREAM FAILED (loud, no brief written): {e}", err=True)
        sys.exit(1)
    click.echo(f"brief: {res.brief_rel_path}"
               + (" (dry-run, not written)" if dry_run else ""))
    click.echo(f"signals used: {res.signals_used} | threads: {res.threads_used} "
               f"| scratch deleted: {res.scratch_deleted}")


@cortex.command("install-nightly")
@click.option("--hour", default=3, show_default=True)
@click.option("--minute", default=30, show_default=True)
@click.option("--uninstall", is_flag=True, default=False)
@vault_option
def cortex_install_nightly(hour: int, minute: int, uninstall: bool,
                           vault: str | None) -> None:
    """Install (or remove) the launchd nightly dream job (macOS only)."""
    import subprocess
    if sys.platform != "darwin":
        click.echo("cortex install-nightly uses launchd and is macOS-only.\n"
                   "On Windows/Linux, schedule `weave-cli cortex dream` with "
                   "Task Scheduler or cron instead.", err=True)
        sys.exit(1)
    from .pro.dreamer import launchd_plist, PLIST_LABEL
    plist_path = Path("~/Library/LaunchAgents").expanduser() / f"{PLIST_LABEL}.plist"
    if uninstall:
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        plist_path.unlink(missing_ok=True)
        click.echo(f"removed {plist_path}")
        return
    v = _resolve_vault_strict(vault)
    python_bin = str(Path(sys.executable).resolve())
    log_path = str(Path("~/Library/Logs/theweave-cortex-nightly.log").expanduser())
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        launchd_plist(str(v.root), python_bin, hour, minute, log_path),
        encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(plist_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        click.echo(f"launchctl load failed: {proc.stderr.strip()}", err=True)
        sys.exit(1)
    click.echo(f"installed {plist_path} — nightly at {hour:02d}:{minute:02d}, "
               f"log {log_path}")


# ---------- bench (Cortex W0: measure first) ----------

@cli.group()
def bench() -> None:
    """Retrieval benchmark harness (LongMemEval-style, Cortex W0)."""


@bench.command("run")
@click.option("--probes", "-p", "probes_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="YAML probe file (see weave/pro/bench.py docstring).")
@click.option("--retriever", "-r", default="all",
              type=click.Choice(["ppr", "keyword", "hybrid", "all"]), show_default=True)
@click.option("--top", "-k", default=8, show_default=True, help="Cutoff k.")
@click.option("--out", "-o", default=None,
              type=click.Path(dir_okay=False),
              help="Append the markdown report to this file.")
@click.option("--show-failures/--no-show-failures", default=True, show_default=True)
@click.option("--fake-embedder", is_flag=True, default=False, hidden=True)
@vault_option
def bench_run(probes_path: str, retriever: str, top: int, out: str | None,
              show_failures: bool, fake_embedder: bool, vault: str | None) -> None:
    """Run the probe set against the current read path; print per-category numbers."""
    from .pro.bench import RETRIEVERS, load_probes, run_bench
    v = _resolve_vault(vault)
    probes = load_probes(probes_path)
    names = list(RETRIEVERS) if retriever == "all" else [retriever]
    kwargs_by_name: dict[str, dict] = {}
    if fake_embedder:
        from .pro.embedder import FakeEmbedder
        kwargs_by_name["hybrid"] = {"embedder": FakeEmbedder()}
    blocks: list[str] = []
    for name in names:
        try:
            report = run_bench(v, probes, name, k=top,
                               retriever_kwargs=kwargs_by_name.get(name))
        except RuntimeError as e:
            if retriever == "all":
                click.echo(f"(skipping {name}: {e})\n")
                continue
            raise
        blocks.append(report.to_markdown())
        click.echo(report.to_markdown())
        click.echo()
        if show_failures:
            fails = report.failures()
            if fails:
                click.echo(f"failures ({name}):")
                for f in fails:
                    click.echo(f"  - {f}")
                click.echo()
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("\n\n".join(blocks) + "\n")
        click.echo(f"report appended to {out}")


# ---------- mcp ----------

@cli.command("mcp")
@vault_option
def mcp_run(vault: str | None) -> None:
    """Start the Weave Core MCP server (stdio transport)."""
    if vault:
        os.environ["WEAVE_VAULT_PATH"] = vault
    elif not os.environ.get("WEAVE_VAULT_PATH"):
        os.environ["WEAVE_VAULT_PATH"] = str((Path(__file__).parent.parent / "seed-vault").resolve())
    from .mcp_server import build_server
    build_server().run()


def main() -> None:
    cli(prog_name="weave")


if __name__ == "__main__":
    main()
