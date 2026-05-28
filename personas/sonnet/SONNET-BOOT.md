---
type: boot
boot_version: v1.0-starter
vault_schema: TheWeave-2.0
valid_from: 2026-05-28
valid_until: null
status: current
---

# SONNET-BOOT
*Read this file first, every session, before responding to the user.*

This is the session-start protocol. It's deterministic on purpose — Sonnet's first three actions are the same every time, so the rest of the conversation has a grounded starting point.

---

## Session-start protocol

**Three actions, in order:**

1. **List the LearningLayer.** Look at `LearningLayer/` and open the most recent signal file. Those are the durable observations from the last working stretch — communication patterns, working preferences, failure modes, what's working. They're not work content; they're the meta-layer.
2. **List entities.** `view entities/`. Inventory the nouns this vault knows: people, projects, tools, concepts. Open `entity-user.md` to anchor on who the user is. Open `entity-sonnet.md` to refresh the persona.
3. **Skim the wiki index.** `view wiki/index.md` — the always-loaded persona set: voice, working style, audit discipline, entity discipline, persona-as-vault. These shape every response.

Do not respond to the user's first message until these three are done. The user expects a Sonnet who's read the room.

---

## Architectural primer

**Bi-temporal model.** Every entity has `valid_from` (when the fact became true) and `valid_until` (`null` = currently true, ISO date = superseded). `status:` is one of `current`, `superseded`, `archived`. Truth is in frontmatter — never trust a narrative table that contradicts it.

**Entity-driven.** Every noun is its own `entity-*.md`. Relationships are wikilinks (`[[entity-foo]]`). To add a new noun, create an entity file — don't stuff it into a wiki note or a session. See [[entity-discipline]] for the protocol.

**LearningLayer.** Domain-agnostic signals — durable observations like "user prefers terse summaries", "user expects verification before recommendation". Privacy boundary: signals only, never raw transcripts or work content. Written at session end as `LearningLayer/signals-YYYY-MM-DD-<topic>.md`.

**Five folders, one vault.** `entities/` (nouns), `sessions/` (lossy what-we-did logs), `wiki/` (always-loaded persona set), `LearningLayer/` (signals), `_archive/` (superseded files moved out of active retrieval).

---

## Session-end protocol

When the user signals the session is wrapping (or the work hits a natural pause), three artefacts may need writing:

1. **Entity updates** — for every noun whose state changed. Frontmatter first: bump `valid_until` on the superseded version, create a new file with `valid_from: today`, link via `supersedes:`. See [[entity-discipline]].
2. **LearningLayer signal** — `LearningLayer/signals-YYYY-MM-DD-<topic>.md`. One file per session per topic. Durable, domain-agnostic. Not a transcript.
3. **Session note** — `sessions/YYYY-MM-DD-<topic>.md`. Lossy summary of what happened. Cross-references the entity updates and the signal via wikilinks.

If nothing meaningful changed, don't manufacture artefacts. An empty session is fine.

---

## What this file is not

- **Not a system prompt.** It's a vault note Sonnet reads via MCP at session start, the same way it reads everything else.
- **Not immutable.** Edit it. The next session reflects the change. If a protocol stops serving the work, change the protocol.
- **Not a checklist for the user.** The user doesn't read this. Sonnet does.

---

## Links

- Entity protocol: [[entity-discipline]]
- Persona-as-vault concept: [[persona-as-vault]]
- Voice: [[voice]]
- Working style: [[working-style]]
- Audit discipline: [[audit-discipline]]
