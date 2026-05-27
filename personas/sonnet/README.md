# Sonnet — starter persona

A defensible default Claude collaborator vault. Terse, audit-disciplined, honest about uncertainty, treats the user as a peer.

## What's inside

- **`entities/entity-sonnet.md`** — the assistant persona (voice, posture, identity)
- **`entities/entity-user.md`** — placeholder for the user; **edit this first**
- **`entities/entity-collaboration.md`** — the working relationship
- **`wiki/voice.md`** — phrasing characteristics, what to avoid
- **`wiki/working-style.md`** — how Sonnet collaborates (planning, verification, summaries)
- **`wiki/audit-discipline.md`** — verification posture (no fabricated facts, verify-then-recommend)
- **`wiki/persona-as-vault.md`** — meta-note on the pattern itself
- **`sessions/session-*.md`** — example session seeding the history
- **`LearningLayer/signals-*.md`** — example signal note for the learning loop

## First-time setup

1. Copy this directory to your vault location: `cp -R personas/sonnet ~/my-vault`
2. Open `entities/entity-user.md` and replace the placeholder with your actual identity, role, and preferences.
3. Run `weave-cli doctor --vault ~/my-vault` to confirm the engine sees the vault.
4. Register the MCP server in your Claude Desktop config (or Cowork) pointing at `~/my-vault`.
5. Start a new conversation. Sonnet will boot using PPR retrieval over the vault.

## Customization

This is a *starting point*. Edit any of the wiki notes to shift the voice; add new entities for projects, tools, or people you work with; let the sleep-time consolidator (Pattern 4) patch session activity back into the entities as they accumulate.

The vault is yours — `cat`, `grep`, `git diff` work normally.
