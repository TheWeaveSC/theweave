"""hydrate(manifest) -> str.

Pure string builder. NO agent spawn, NO network, NO WeaveCore write. This
is the "arm-on-connect" text render: deterministic, so the SessionStart
hook can shell out to `weave-cli team hydrate` and append the output to
additionalContext with zero idle token spend — arming is context
injection only.
"""

from __future__ import annotations

from .models import TeamManifest, Tier

CHAIRMAN_LANE = (
    "Chairman lane: gate, sequence, adjudicate, synthesize — never IC, "
    "never build, never dig. On seat crash, re-dispatch the seat; the "
    "chairman does not silently absorb the IC work."
)


def hydrate(manifest: TeamManifest) -> str:
    """Render the armed protocol markdown block."""
    lines: list[str] = []
    lines.append("# Org Team — armed protocol (hydrated from Weave)")
    lines.append("")
    lines.append(
        "Reaching weave-core arms the team: roster + loop + routing are now "
        "in context. No agent has been spawned; zero tokens spent until a "
        "task is assigned."
    )
    lines.append("")

    # Roster table
    lines.append("## Roster")
    lines.append("")
    lines.append("| Seat | Role | Tier | When to use |")
    lines.append("|---|---|---|---|")
    for seat in manifest.seats:
        lines.append(
            f"| {seat.name} | {seat.role} | {seat.default_tier.value} "
            f"({seat.default_tier.model_id}) | {seat.when_to_use} |"
        )
    lines.append("")

    # Loop
    lines.append("## Governance loop")
    lines.append("")
    lines.append(
        "propose -> cross-attack -> consolidate -> chairman-attack -> "
        "governance-gate"
    )
    lines.append("")
    lines.append("| Phase | Mechanic |")
    lines.append("|---|---|")
    for phase in manifest.loop_phases:
        lines.append(f"| {phase.name} | {phase.mechanic} |")
    lines.append("")

    # Routing policy
    lines.append("## Routing policy")
    lines.append("")
    lines.append("| Tier | Model |")
    lines.append("|---|---|")
    for tier in Tier:
        lines.append(f"| {tier.value} | {tier.model_id} |")
    lines.append("")
    lines.append(
        f"Default tier if nothing declared: {manifest.routing_policy.default_tier.value} "
        f"({manifest.routing_policy.default_tier.model_id})."
    )
    lines.append(
        "Precedence: explicit task override > cue-word match > seat default_tier > engine default."
    )
    lines.append("")

    # Hard floors
    lines.append("## Hard-floor invariants")
    lines.append("")
    for floor in manifest.hard_floors:
        lines.append(f"- {floor}")
    lines.append("")

    # Chairman lane
    lines.append("## Chairman lane")
    lines.append("")
    lines.append(CHAIRMAN_LANE)
    lines.append("")

    return "\n".join(lines)


__all__ = ["hydrate", "CHAIRMAN_LANE"]
