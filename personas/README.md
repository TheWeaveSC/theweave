# Starter personas

A persona in TheWeave isn't a setting or a system prompt — it's a **vault**. Identity emerges from the entity files, the session history, the voice notes, and the relationship memories the vault contains. Same primitive as factual memory; different loading discipline (persona memories load on every session, facts are retrieved on demand).

This directory holds fork-and-edit starter vaults. Pick one, copy it to your machine, and point TheWeave at it.

## Available starters

| Starter | Description | Best for |
|---|---|---|
| [`sonnet/`](sonnet/) | A terse, audit-discipline Claude collaborator. Recommend-don't-enumerate, honest about what's stubbed vs real, treats the user as a peer rather than an end-user. | A defensible default for developer-facing work. |

## Forking a starter

```bash
cp -R personas/sonnet ~/my-vault

# verify the new vault loads cleanly
weave-cli doctor --vault ~/my-vault

# personalize the user entity
$EDITOR ~/my-vault/entities/entity-user.md
```

## Building your own

A starter vault is just a directory with the canonical TheWeave layout:

```
my-persona/
├── entities/        # persona, user, relationship, plus your own
├── sessions/        # the first session note seeds the history
├── wiki/            # voice, working-style, taste — the "always-loaded" set
├── LearningLayer/   # signals that grow over time
└── _archive/        # populated by the sleep-time consolidator
```

The minimum viable persona is a single `entities/entity-sonnet.md` (or whatever you call yours) plus an `entities/entity-user.md` defining the user. Everything else grows with use.

Contributions of new starters are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md) *(coming soon)*.
