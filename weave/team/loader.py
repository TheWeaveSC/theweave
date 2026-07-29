"""Load a TeamManifest from either the in-repo templates dir or a Vault.

`source` accepts:
  - None (default): the in-repo `templates/team/` directory, so `team
    hydrate` / `team list` work with no vault at all.
  - a `Vault` instance: reads `entity-Team-Hub.md` etc. from the vault's
    `entities/` (or vault root, if that's where `team install` put them).
  - a str/Path: treated as a plain directory of markdown templates (used
    directly by tests and by the default templates dir).

Deterministic seat ordering: seats are returned sorted by name, so
hydrate() output is byte-identical across calls regardless of filesystem
iteration order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import frontmatter

from .models import (
    CANONICAL_HARD_FLOORS,
    CANONICAL_LOOP_PHASES,
    LoopPhase,
    RoutingPolicy,
    Seat,
    TeamManifest,
    TeamManifestError,
    Tier,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "team"

_LOOP_MECHANICS = {
    "Intake": "propose",
    "Plan": "propose",
    "Execute": "cross-attack (attack-peers-not-self)",
    "GovernanceGate": "chairman-attack (reproduce-on-real-tool)",
    "Converge": "consolidate",
    "Settle": "gate",
}


class _TemplateSource:
    """Uniform read interface over either a plain directory or a Vault."""

    def __init__(self, source: "str | Path | object | None"):
        if source is None:
            self._dir = TEMPLATES_DIR
            self._vault = None
        elif hasattr(source, "iter_notes") and hasattr(source, "load_note"):
            # duck-typed Vault
            self._dir = None
            self._vault = source
        else:
            self._dir = Path(source)
            self._vault = None

    def label(self) -> str:
        return str(self._vault.root) if self._vault is not None else str(self._dir)

    def iter_team_files(self) -> Iterable[tuple[str, dict, str]]:
        """Yield (rel_path, metadata, body) for every team entity file
        found — i.e. every markdown file whose stem starts with
        'entity-Team-', 'entity-OrgTeam-', or 'entity-seat-'.
        """
        if self._vault is not None:
            for note in self._vault.iter_notes():
                if _is_team_file(note.name):
                    yield note.rel_path, note.metadata, note.content
        else:
            if not self._dir.is_dir():
                raise TeamManifestError(f"template source directory not found: {self._dir}")
            for path in sorted(self._dir.rglob("*.md")):
                if _is_team_file(path.stem):
                    post = frontmatter.load(path)
                    rel = str(path.relative_to(self._dir))
                    yield rel, dict(post.metadata), post.content


def _is_team_file(stem: str) -> bool:
    return (
        stem.startswith("entity-Team-")
        or stem.startswith("entity-OrgTeam-")
        or stem.startswith("entity-seat-")
    )


def _require(md: dict, field: str, rel: str) -> object:
    if field not in md or md[field] in (None, ""):
        raise TeamManifestError(f"{rel}: missing required field {field!r}")
    return md[field]


def _parse_seat(rel: str, md: dict, body: str) -> Seat:
    name = _require(md, "seat_name", rel)
    role = _require(md, "role", rel)
    roster = _require(md, "roster", rel)
    default_tier_raw = _require(md, "default_tier", rel)
    when_to_use = _require(md, "when_to_use", rel)
    caps = md.get("capabilities") or []
    if not isinstance(caps, list):
        raise TeamManifestError(f"{rel}: 'capabilities' must be a list")

    try:
        tier = Tier.from_str(str(default_tier_raw))
    except TeamManifestError as e:
        raise TeamManifestError(f"{rel}: {e}") from e

    persona = _extract_persona(body)

    return Seat(
        name=str(name),
        role=str(role),
        roster=str(roster),
        persona=persona,
        capabilities=tuple(str(c) for c in caps),
        default_tier=tier,
        when_to_use=str(when_to_use),
        rel_path=rel,
    )


def _extract_persona(body: str) -> str:
    """Pull the 'Persona summary.' line out of a seat body, if present."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("**persona summary.**"):
            return stripped.split("**", 2)[-1].strip(" .") or stripped
    return ""


def _parse_hub(rel: str, md: dict) -> int:
    version = _require(md, "manifest_version", rel)
    try:
        return int(version)
    except (TypeError, ValueError) as e:
        raise TeamManifestError(f"{rel}: manifest_version must be an int, got {version!r}") from e


def _build_loop_phases() -> tuple[LoopPhase, ...]:
    # Canonical phases are structural (fixed by the protocol), not
    # free-form vault content — encoded once in models.py and rendered
    # here with their practised mechanic, matching entity-Team-Loop.md.
    return tuple(
        LoopPhase(name=name, mechanic=_LOOP_MECHANICS[name])
        for name in CANONICAL_LOOP_PHASES
    )


def _build_routing_policy(md: dict, rel: str) -> RoutingPolicy:
    tiers = md.get("tiers") or {}
    if not isinstance(tiers, dict) or not tiers:
        raise TeamManifestError(f"{rel}: routing policy missing 'tiers' mapping")
    default_tier_raw = md.get("default_tier", "sonnet-5")
    # entity-Team-Routing.md's default_tier is expressed as a MODEL name
    # (sonnet-5), not a tier label — map it back to the STANDARD tier.
    default_tier = Tier.STANDARD
    for label, model in tiers.items():
        if model == default_tier_raw:
            default_tier = Tier.from_str(label)
            break
    return RoutingPolicy(tiers={k: str(v) for k, v in tiers.items()}, default_tier=default_tier)


def load_manifest(source=None) -> TeamManifest:
    """Load and validate a TeamManifest from `source`.

    `source`: None (in-repo templates), a Vault, or a directory path.
    """
    ts = _TemplateSource(source)
    files = list(ts.iter_team_files())
    if not files:
        raise TeamManifestError(f"no team entity files found under {ts.label()}")

    hub_md = None
    hub_rel = None
    seats: list[Seat] = []
    routing_md = None
    routing_rel = None
    governance_champion = ""
    found_sop = False

    for rel, md, body in files:
        stem = Path(rel).stem
        if stem == "entity-Team-Hub":
            hub_md, hub_rel = md, rel
            governance_champion = str(md.get("governance_champion") or "")
        elif stem == "entity-Team-Routing":
            routing_md, routing_rel = md, rel
        elif stem == "entity-OrgTeam-SOP":
            found_sop = True
        elif stem.startswith("entity-seat-"):
            seats.append(_parse_seat(rel, md, body))
        elif stem == "entity-Team-Loop":
            pass  # canonical phases are structural; see _build_loop_phases
        else:
            continue

    if hub_md is None:
        raise TeamManifestError(f"{ts.label()}: entity-Team-Hub.md not found")
    if not found_sop:
        raise TeamManifestError(f"{ts.label()}: entity-OrgTeam-SOP.md not found")
    if routing_md is None:
        raise TeamManifestError(f"{ts.label()}: entity-Team-Routing.md not found")
    if not seats:
        raise TeamManifestError(f"{ts.label()}: no entity-seat-*.md files found")

    hub_version = _parse_hub(hub_rel, hub_md)
    routing_policy = _build_routing_policy(routing_md, routing_rel)
    loop_phases = _build_loop_phases()

    seats.sort(key=lambda s: s.name)

    return TeamManifest(
        hub_version=hub_version,
        seats=tuple(seats),
        loop_phases=loop_phases,
        hard_floors=CANONICAL_HARD_FLOORS,
        routing_policy=routing_policy,
        governance_champion=governance_champion,
    )


__all__ = ["load_manifest", "TEMPLATES_DIR"]
