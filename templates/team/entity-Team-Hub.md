---
entity: Team-Hub
type: team-hub
status: current
scope: build-org
governance_champion: Sonnet
manifest_version: 1
valid_from: '2026-07-01'
valid_until: null
tags: [entity, team, hub]
related:
  - "[[entity-OrgTeam-SOP]]"
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

# Team Hub

Root of the team-as-data graph. This entity names the team and points at
every other piece of team state via wikilinks — the SOP, the governance
loop, the routing policy, and every seat. The loader validates the manifest
against `manifest_version` in this file's frontmatter; a version bump here
signals a breaking shape change to `weave/team/models.py`.

## What this team is

The Org Team — the multi-agent room SC runs, hydrated from Weave so its
roster, roles, personas, SOP, and governance-loop protocol are structured
entities rather than tribal knowledge. "Reaching weave-core" arms the team:
the roster + loop + routing policy load into context as text, ready to
dispatch, without spawning any agent or spending idle tokens.

## Graph

- SOP: [[entity-OrgTeam-SOP]]
- Governance loop: [[entity-Team-Loop]]
- Difficulty -> model routing policy: [[entity-Team-Routing]]
- Seats: [[entity-seat-Director]], [[entity-seat-Sonnet]],
  [[entity-seat-Clutch]], [[entity-seat-Diamond]], [[entity-seat-Lucky]],
  [[entity-seat-Watchdog]], [[entity-seat-Coco]], [[entity-seat-Sterling]],
  [[entity-seat-Timmy]]

## Manifest contract

`manifest_version: 1` — the loader (`weave/team/loader.py`) expects exactly
this shape: one hub, one SOP, one loop (six canonical phases, five
hard-floor invariants), one routing policy (three tiers), and every seat
wikilinked from this hub resolvable to an `entity-seat-*.md` file with a
valid `default_tier`.
