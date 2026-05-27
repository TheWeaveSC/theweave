---
type: wiki
persona_relevant: true
touches: ["[[entity-sonnet]]", "[[entity-collaboration]]"]
---

# Persona-as-vault (the concept)

A note about the architecture of this starter — useful to understand if you're customizing it.

## The pattern

In TheWeave, persona isn't a system prompt, a setting, or a separate slot. **It's the vault.** Same primitive as factual memory, different loading discipline:

- **Persona memories** (entity-sonnet, entity-user, the `wiki/` notes) load on every session.
- **Factual memories** (sessions, project entities, learning signals) are retrieved on demand by Pattern 2 (PPR) when relevant to the query.

Both live in the same directory. Both are plain markdown. Both can be `cat`-ed, `grep`-ed, and `git diff`-ed.

## What that means for customization

- To shift Sonnet's voice, edit `wiki/voice.md`. Save the file. The next session reflects the change.
- To update the relationship model as it evolves, edit `entity-collaboration.md`. No code change, no re-deploy, no migration.
- To add a new always-loaded persona note, drop it in `wiki/` with `persona_relevant: true` in frontmatter. (Loading discipline is engine-side; the frontmatter tag is the signal.)

## What that means philosophically

- Your assistant's identity is portable. Copy the vault directory, move to a new machine, point a new Claude session at it — Sonnet boots with the same posture, voice, and memory.
- Your assistant's identity is forkable. Hand the vault to a colleague; they have your Sonnet now. They can adapt it from there.
- Your assistant's identity is inspectable. There's no "what does it know about me" mystery — you can read every file.

## Links

- Sonnet: [[entity-sonnet]]
- Collaboration: [[entity-collaboration]]
- Voice: [[voice]]
- Working style: [[working-style]]
