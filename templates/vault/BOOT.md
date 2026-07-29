---
type: boot
status: current
valid_from: null
valid_until: null
---

# BOOT — session rituals & conventions

Lean index node for this vault. This file describes HOW to work in this
vault; it does not carry project content itself. See `entities/index.md`
for the live roster of what's actually in here.

## Session-start ritual

On connect, before doing any task work:

1. **Reach weave-core.** Connecting to the `weave-core` MCP server also
   arms the Org Team engine (roster + governance loop + routing land in
   context automatically via `weave-cli team hydrate`). Reaching the tool
   is enough — no separate step needed.
2. **View the vault root and `entities/index.md`.** Use `view` on the
   vault root, then on `entities/index.md`, before assuming anything
   about what state exists. Treat the index as the lean entry node, not
   as a cache to trust blindly — it points at entities, it doesn't
   replace reading them.
3. **Run a boot query for the active thread before acting.** Retrieve
   relevant entities/sessions/signals for whatever the user is about to
   ask, rather than acting from a cold context.

## Session-end ritual

Before closing out a working session:

1. **Write a session note.** Create `sessions/session-<YYYY-MM-DD>-<slug>.md`
   with `type: session` frontmatter and a `touches:` list of `[[wikilink]]`
   references to every entity the session materially affected.
2. **Propose, don't silently rewrite.** If a durable correction surfaced
   (a fact was wrong, a decision changed), propose a new LearningLayer
   signal describing it. Do not silently edit a locked/status:current
   entity out from under its history — the bi-temporal model expects a
   superseding note, not an in-place rewrite.
3. **Update the index.** Add the new session (and any new/changed
   entities) to `entities/index.md` so the next session-start ritual
   finds it.

## Conventions (ENFORCED)

- **Basename-only wikilinks.** Always write `[[entity-Foo]]`, never a
  path or a file extension. The wikilink graph matches on note basename
  (stem) only; a path- or extension-qualified link will not resolve to
  an edge and will silently fail to connect notes.
- **Machine-suffixed LearningLayer filenames.** Name signal files
  `signals-<YYYY-MM>[-<machine-suffix>].md` so two concurrent writers
  never collide on the same physical file. The suffix can be a session
  id, a short slug, or a sequence letter — the only requirement is that
  it disambiguates from any other writer's file for the same month.
- **Bi-temporal entity frontmatter.** Every `entities/entity-*.md` note
  carries `status`, `valid_from`, and `valid_until` in its frontmatter,
  even when `valid_until` is `null` (still current). This is what lets
  the bi-temporal resolver walk supersession chains and what the doctor's
  bi-temporal coverage check measures.

## Governance-loop protocol

This vault's Org Team engine (installed under `entities/`) runs a
six-phase governance loop: **Intake -> Plan -> Execute -> GovernanceGate
-> Converge -> Settle**, with a fixed set of hard-floor invariants that
hold regardless of seat or time pressure. The full protocol — phases,
practised mechanics, and hard floors — lives in `[[entity-Team-Loop]]`
and the operating procedure in `[[entity-OrgTeam-SOP]]`; this file only
points at them so BOOT.md itself stays a lean index rather than a
duplicate of that content.

See also: `[[entity-Team-Hub]]` (roster entry point), `[[entity-Team-Routing]]`
(difficulty -> model routing policy).
