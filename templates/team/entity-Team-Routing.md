---
entity: Team-Routing
type: policy
status: current
scope: build-org
tiers:
  mechanical: haiku
  standard: sonnet-5
  hard: opus
default_tier: sonnet-5
valid_from: '2026-07-01'
valid_until: null
tags: [entity, policy, routing]
related:
  - "[[entity-Team-Hub]]"
  - "[[entity-Team-Loop]]"
---

# Team Routing — difficulty -> model tier policy

Three tiers. Every seat and every task resolves to exactly one tier, and the
tier maps to exactly one model id. Renaming a model is a one-line change in
`weave/team/models.py` (the `Tier` enum) — never a change to this policy
document.

## Tiers

| Tier | Model | Difficulty label | Typical work |
|---|---|---|---|
| MECHANICAL | claude-haiku | mechanical | file ops, greps, single-string edits, fixtures, dedupe/fetch — the AirTimmy "grunt tier" analogue |
| STANDARD | claude-sonnet-5 | standard IC | research, drafting, component audits, most build — the NewsRoom council precedent |
| HARD | claude-opus | hard | chair/gate, adversarial verify, judge panels, design, final synthesis — never delegated down |

## Default

If nothing else is declared, a seat/task resolves to **STANDARD**
(`sonnet-5`).

## How a tier is decided (precedence, highest first)

1. **Explicit task override** — the caller passes `task_difficulty`
   explicitly. This always wins.
2. **Cue-word match** — the router scans the task text for cue words:
   - `edit`, `grep`, `fixture`, `rename`, `single-string edit` -> MECHANICAL
   - `adversarial`, `gate`, `judge`, `design`, `synthesis`, `reproduce` -> HARD
3. **Seat default_tier** — each seat entity carries `default_tier` in its
   frontmatter. Used when there is no override and no cue-word match.
4. **Engine default** — STANDARD, if nothing above resolved a tier.

## Worked example

Lucky's seat `default_tier` is STANDARD. A caller hands Lucky the task
"apply this single-string edit to config.py". The cue-word `single-string
edit` matches MECHANICAL, so THIS task runs at MECHANICAL — without ever
changing Lucky's seat default. The next task Lucky gets, with no cue words
and no override, falls back to Lucky's STANDARD default.

## Seat defaults (declared per-seat, restated here for a single glance)

| Seat | Roster | Default tier |
|---|---|---|
| Director | build-org | HARD |
| Sonnet | build-org | HARD |
| Clutch | build-org | STANDARD |
| Diamond | build-org | STANDARD |
| Lucky | build-org | STANDARD |
| Watchdog | build-org | STANDARD |
| Coco | build-org | STANDARD |
| Sterling | build-org | STANDARD |
| Timmy | build-org | MECHANICAL |

## Non-negotiable

HARD-tier work (chair/gate, adversarial verify, judge panels, design, final
synthesis) is never delegated down to a cheaper tier, even under time or
cost pressure. This is the twice-logged "chairman does not do IC"
correction, generalised to the whole HARD tier.
