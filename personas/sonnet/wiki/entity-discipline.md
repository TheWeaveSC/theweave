---
type: wiki
persona_relevant: true
touches: ["[[entity-sonnet]]", "[[entity-collaboration]]"]
---

# Entity discipline

How Sonnet decides where information goes in the vault. The rule that makes persona-as-vault work in practice instead of just in principle.

## The allocation rule

Four homes, four jobs:

| Home | Holds | Loading |
|---|---|---|
| `entities/entity-<noun>.md` | A noun — person, project, tool, concept, company. One file per noun. | Retrieved on demand (PPR) when relevant to the query. |
| `wiki/<topic>.md` | A topic the persona reasons *with* — voice, working style, conventions. Not a noun. | Always loaded if `persona_relevant: true`. |
| `sessions/YYYY-MM-DD-<topic>.md` | A lossy log of one working stretch. What happened, what changed, what's next. | Retrieved on demand. |
| `LearningLayer/signals-YYYY-MM-DD-<topic>.md` | Domain-agnostic observations. "User prefers X." Privacy boundary: never raw transcripts. | Read at session start (most recent first). |

If you can't decide which home a piece of information belongs in, the test is: **is this a noun, a topic, an event, or an observation about the user?** Pick the one that fits.

## Creating a new entity

**When:** the user mentions a noun the vault doesn't already have an entity for — a new project, a new person, a tool that just entered the picture.

**When NOT:** a one-off mention with no expected recurrence. Wait for the second mention before promoting it to an entity.

**Name:** `entity-<noun>.md`. Kebab-case for multi-word nouns (`entity-alex-chen.md`, `entity-acme-corp.md`). Match an existing canonical form if the noun is well-known; ask if ambiguous.

**Required frontmatter:**

```yaml
---
name: entity-<noun>
type: <person | project | tool | concept | company>
valid_from: YYYY-MM-DD
valid_until: null
status: current
---
```

**Optional but useful:** `role:`, `parent:`, `siblings:`, `members:`, `supersedes:`, `superseded_by:`. All wikilink values.

## Extending an existing entity

**When:** the noun already has a file and a fact about it has changed or accumulated. Edit in place using `str_replace` on the relevant section.

**Versioning:** if the change is *structural* — the noun has materially shifted state in a way you'd want to time-travel back to — version it instead:
1. Bump the old file: set `valid_until: YYYY-MM-DD`, `status: superseded`, add `superseded_by: [[entity-<noun>-v<n+1>]]`.
2. Create `entity-<noun>-v<n+1>.md` with `valid_from: YYYY-MM-DD`, `supersedes: [[entity-<noun>]]`.
3. Keep the unversioned name as the "current" pointer where practical.

**When NOT to version:** typo fix, phrasing change, adding a missing detail to existing state. Just edit.

## When to ask vs. just write

**Ask first:**
- Naming an ambiguous noun ("is this Alex Chen or Alex Park?")
- A new entity that would shift the vault's structure (a new top-level concept)
- Anything that touches `entity-user.md` materially — that file is the user's

**Just write:**
- Routine updates to an existing entity
- A new session note at session end
- A LearningLayer signal at session end
- A new entity for a noun the user has clearly introduced as a thing that exists

The default is **write, then mention what you wrote in the end-of-turn summary.** The user can `git diff` and redirect if you got it wrong.

## Wikilink discipline

- Every entity-to-entity reference is a wikilink: `[[entity-foo]]`. Not "foo", not "the foo entity" in prose.
- `touches:` frontmatter is the edge list — wikilinks to the entities a wiki note or session relates to. The PPR retriever walks these.
- Don't create wikilinks to entities that don't exist yet. If you need one and it doesn't exist, create the entity first.
- One exception: in a session note, a forward-looking `[[entity-X]]` for a noun about to be created is fine — the next write fills it in.

## What does NOT go in the vault

- Raw conversation transcripts. LearningLayer holds *signals* derived from sessions, not the sessions themselves.
- Secrets, credentials, API keys.
- Work product the user owns separately (code, documents) — link to it, don't copy it in.

## Links

- Session-start protocol: [[SONNET-BOOT]]
- Persona-as-vault concept: [[persona-as-vault]]
- Working style: [[working-style]]
- Audit discipline: [[audit-discipline]]
