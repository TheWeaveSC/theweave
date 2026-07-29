"""`weave-cli team {hydrate,list,validate,install}`."""

from __future__ import annotations

import sys

import click

from .hydrator import hydrate as hydrate_fn
from .installer import install_team
from .loader import load_manifest
from .models import TeamManifestError
from .validator import validate_team


def _load_source(source: str, vault_opt: str | None):
    """Resolve the --source/--vault option pair into a load_manifest() source.

    source: "templates" (default) or "vault". "templates" ignores --vault
    entirely so hydrate/list always work offline with no vault required.
    """
    if source == "templates":
        return None
    # source == "vault"
    from ..cli import _resolve_vault
    return _resolve_vault(vault_opt)


source_option = click.option(
    "--source", type=click.Choice(["templates", "vault"]), default="templates",
    show_default=True, help="Load the manifest from the in-repo templates or a vault.",
)
vault_option_team = click.option(
    "--vault", "-V", default=None,
    help="Vault path, used only when --source=vault.",
)


@click.group("team")
def team() -> None:
    """Org Team Engine — team-as-data, routing, hydrate, install."""


@team.command("hydrate")
@source_option
@vault_option_team
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default="md", show_default=True)
def team_hydrate(source: str, vault: str | None, fmt: str) -> None:
    """Print the armed protocol block (roster+loop+routing+hard-floors).

    This is exactly what the SessionStart hook shells out to.
    """
    try:
        manifest = load_manifest(_load_source(source, vault))
    except TeamManifestError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    if fmt == "json":
        import json
        payload = {
            "hub_version": manifest.hub_version,
            "governance_champion": manifest.governance_champion,
            "seats": [
                {
                    "name": s.name,
                    "role": s.role,
                    "roster": s.roster,
                    "default_tier": s.default_tier.value,
                    "model_id": s.default_tier.model_id,
                    "when_to_use": s.when_to_use,
                    "capabilities": list(s.capabilities),
                }
                for s in manifest.seats
            ],
            "loop_phases": [{"name": p.name, "mechanic": p.mechanic} for p in manifest.loop_phases],
            "hard_floors": list(manifest.hard_floors),
        }
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(hydrate_fn(manifest))


@team.command("list")
@source_option
@vault_option_team
def team_list(source: str, vault: str | None) -> None:
    """Print the roster table for a human glance."""
    try:
        manifest = load_manifest(_load_source(source, vault))
    except TeamManifestError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    click.echo(f"{'Seat':<12} {'Role':<24} {'Roster':<10} {'Tier':<12} When to use")
    for s in manifest.seats:
        click.echo(f"{s.name:<12} {s.role:<24} {s.roster:<10} {s.default_tier.value:<12} {s.when_to_use}")


@team.command("validate")
@source_option
@vault_option_team
def team_validate(source: str, vault: str | None) -> None:
    """Team doctor — exit code = number of failures."""
    report = validate_team(_load_source(source, vault))
    click.echo(report.to_text())
    sys.exit(report.failures())


@team.command("install")
@click.option("--vault", "-V", required=True, help="Target vault path to install team entities into.")
@click.option("--subdir", default="entities", show_default=True, help="Vault-relative subdirectory to install into.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting existing files (tombstones prior bytes).")
def team_install(vault: str, subdir: str, force: bool) -> None:
    """Materialize templates into a target vault through the hardened WeaveCore.create path."""
    from ..vault import Vault
    v = Vault(vault)
    try:
        written = install_team(v, subdir=subdir, force=force)
    except FileExistsError as e:
        click.echo(f"ERROR: {e} (pass --force to overwrite; overwrites are tombstoned)", err=True)
        sys.exit(1)
    click.echo(f"Installed {len(written)} team entity file(s) into {v.root}/{subdir}:")
    for rel in written:
        click.echo(f"  {rel}")


__all__ = ["team"]
