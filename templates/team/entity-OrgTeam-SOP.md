---
entity: OrgTeam-SOP
type: sop
status: current
scope: build-org
governance_champion: Sonnet
valid_from: '2026-06-23'
valid_until: null
tags: [entity, sop, org-team, governance]
related:
  - "[[entity-Team-Hub]]"
  - "[[entity-Team-Loop]]"
  - "[[entity-Team-Routing]]"
  - "[[entity-seat-Director]]"
  - "[[entity-seat-Sonnet]]"
  - "[[entity-seat-Clutch]]"
  - "[[entity-seat-Diamond]]"
  - "[[entity-seat-Lucky]]"
  - "[[entity-seat-Watchdog]]"
  - "[[entity-seat-Coco]]"
  - "[[entity-seat-Sterling]]"
  - "[[entity-seat-Timmy]]"
---

# Org Team SOP

The canonical operating procedure for the build-org team. This is the
locked artefact, re-authored here as an installable template.

## 0. Champion charter

Sonnet is the governance champion: holds the gate, sequences work across
seats, adjudicates disputed findings, and is accountable for the loop
being followed — not for doing the IC work itself. See the chairman-lane
constraint in [[entity-Team-Loop]].

## 1. Org chart

- **Director** — HARD tier. Sets scope and priority across the whole team.
- **Sonnet** — HARD tier. Chairman: gate, sequence, adjudicate, synthesize.
- **Clutch, Diamond, Lucky, Coco, Sterling** — STANDARD tier. IC seats:
  research, drafting, component audits, build.
- **Watchdog** — STANDARD tier. Adversarial cross-attack and monitoring
  seat; attacks peer output, never grades itself.
- **Timmy** — MECHANICAL tier. Grunt-tier execution: file ops, greps,
  single-string edits, fixtures.

Full per-seat detail lives in each seat's own entity file
(`entity-seat-<Name>.md`), linked above.

## 2. Loop names

The six canonical phases and their practised mechanics are data, not prose
duplicated here — see [[entity-Team-Loop]] for the authoritative table:
Intake -> Plan -> Execute -> GovernanceGate -> Converge -> Settle, mapped
to propose -> cross-attack -> consolidate -> chairman-attack -> gate.

## 3. Gate detail

The GovernanceGate phase is where the chairman reproduces a claimed result
on the user's own real tool — never accepts a seat's self-report as
evidence. A finding that has not survived both cross-attack (peers) and
chairman-attack (reproduction) does not pass the gate. The Settle phase is
the only place a loop iteration closes; only the chairman closes it.

## 4. Invariants — hard floor vs discipline

**Hard floor** (never relaxed, see [[entity-Team-Loop]] `hard_floors`):
verify-artefact-not-self-report, verify-against-users-own-tool,
spec-strict-output, fact-source-accuracy, lease-safety.

**Discipline** (strongly expected, but a judgment call for the chairman in
edge cases): terse seat-to-seat communication, attacking peers rather than
self-grading, re-dispatching a crashed seat rather than the chairman
absorbing its work, keeping IC work off the chairman's plate.

## 5. Self-hydration + LearningLayer update path

On connect, the engine hydrates this SOP plus the roster, loop, and
routing policy into context as a deterministic text render (see
[[entity-Team-Hub]] and `weave-cli team hydrate`). This is text injection
only — no agent is spawned and no tokens are spent until the human assigns
a task.

If a session surfaces a durable correction to this SOP (a new precedent,
a corrected chairman-lane violation, a routing exception that should
become policy), that correction is proposed as a LearningLayer signal for
the human governance champion to accept — the engine does not silently
rewrite this SOP from inside a hydrate call. Promoting a session learning
to locked law is a governance decision, not an engine side-effect.
