---
entity: Team-Loop
type: protocol
status: current
scope: build-org
valid_from: '2026-07-01'
valid_until: null
hard_floors:
  - verify-artefact-not-self-report
  - verify-against-users-own-tool
  - spec-strict-output
  - fact-source-accuracy
  - lease-safety
tags: [entity, protocol, governance-loop]
related:
  - "[[entity-Team-Hub]]"
  - "[[entity-OrgTeam-SOP]]"
  - "[[entity-Team-Routing]]"
---

# Team Loop — the governance-loop protocol

The loop as actually practised: **propose -> cross-attack -> consolidate ->
chairman-attack -> governance-gate**. Encoded here as six canonical phases
so an engine (or an LLM reading this entity) can follow it without
re-deriving it from scratch each session.

## Canonical phases

| # | Phase | Practised mechanic | Notes |
|---|---|---|---|
| 1 | Intake | propose | A seat produces a first-pass artefact (design, patch, draft) against the assigned task. |
| 2 | Plan | propose | The seat states scope, approach, and open questions before executing, so the chair can redirect cheaply. |
| 3 | Execute | cross-attack (attack-peers-not-self) | Seats review each other's output adversarially. A seat never grades its own work; peers attack it. |
| 4 | GovernanceGate | chairman-attack (reproduce-on-real-tool) | The chairman re-runs/reproduces the claimed result on the user's own tool — not on the seat's self-report. Nothing is accepted on say-so. |
| 5 | Converge | consolidate | Findings that survive cross-attack and chairman-attack are merged into one authoritative artefact. |
| 6 | Settle | gate | The chairman applies the governance-gate: accept, send back, or escalate. Only the chairman closes the loop. |

## Hard-floor invariants (non-negotiable)

These five hold regardless of time pressure, seat, or tier:

1. **verify-artefact-not-self-report** — a claim of "done" is not evidence;
   the artefact itself (diff, test output, file) is the evidence.
2. **verify-against-users-own-tool** — reproduction happens on the actual
   tool/environment the user runs, not a seat's paraphrase of it.
3. **spec-strict-output** — outputs conform exactly to the requested shape;
   no silent format drift.
4. **fact-source-accuracy** — claims trace to a checkable source; no
   fabricated citations or invented state.
5. **lease-safety** — a single-writer lease governs any write; no seat
   writes outside its held lease.

## Chairman-lane constraint

The chairman (HARD tier, Opus) **gates, sequences, adjudicates, and
synthesizes**. The chairman never does IC work, never builds, never digs.
If a seat crashes mid-task, the chairman re-dispatches the seat (or a
replacement seat) — the chairman does not silently pick up the IC work
itself. This is a twice-logged correction and is treated as a hard
constraint on the chairman lane, not a style preference.
