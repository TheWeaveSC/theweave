---
date: 2026-01-01
type: session
touches: ["[[entity-sonnet]]", "[[entity-user]]", "[[entity-collaboration]]"]
---

# Bootstrap session

The first session in the vault. Establishes the relationship and the working defaults.

This file exists so the Pattern 2 PPR retriever has at least one session edge in the graph at first boot. Replace it (or add to it) with real session notes as you work.

## Context

User installed TheWeave, cloned the Sonnet starter vault, edited `entity-user.md` to reflect their identity, and opened the first conversation with Sonnet wired up.

## Established

- Voice and working-style defaults loaded from `wiki/` notes
- User's preferences (length, depth, decision style) live in [[entity-user]]
- Collaboration model in [[entity-collaboration]] sets defaults that don't need re-negotiating

## Next

Real session notes will land here as the user works. The sleep-time consolidator (Pattern 4) will patch session activity back into the relevant entity files; the conflict resolver (Pattern 5) will prevent duplicates as the vault grows.
