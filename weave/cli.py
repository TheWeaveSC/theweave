"""Weave 2.0 sandbox CLI — `weave demo …` entry-point.

All commands operate against a vault directory chosen via:
  1. --vault flag, OR
  2. WEAVE_VAULT_PATH env var, OR
  3. default `./seed-vault` relative to the sandbox root.
"""

from __future__ import annotations

import os
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
    for n in notes:
        top = n.rel_path.split("/", 1)[0]
        by_dir[top] = by_dir.get(top, 0) + 1

    from .pro.llm import is_mock
    mode = "MOCK (offline — set ANTHROPIC_API_KEY to switch)" if is_mock() else "Claude (live API)"

    click.echo("🪶 Weave 2.0 — sandbox")
    click.echo(f"  vault: {v.root}")
    click.echo(f"  notes: {len(notes)} across {len(by_dir)} top-level folders")
    for k, n in sorted(by_dir.items()):
        click.echo(f"    {k}/: {n}")
    click.echo("")
    click.echo("Pattern wiring:")
    click.echo("  1. Weave Core 5-verb MCP   ✅ (run `weave mcp` or `python -m weave.mcp_server`)")
    click.echo("  2. PPR boot retriever       ✅ (`weave demo boot <query>`)")
    click.echo("  3. Bi-temporal resolver     ✅ (`weave demo current <name>`)")
    click.echo("  4. Sleep-time consolidator  ✅ (`weave demo consolidate [--apply]`)")
    click.echo("  5. Write-time conflict      ✅ (`weave demo write <file>`)")
    click.echo("")
    click.echo(f"LLM mode: {mode}")


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
    """Pattern 2 — Personalized PageRank boot retrieval, seeded by the query."""
    from .pro.ppr import PPRBoot
    v = _resolve_vault(vault)
    ppr = PPRBoot(v)
    ppr.build()
    q = " ".join(query)
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
