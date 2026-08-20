# Migrating an Obsidian vault into TheWeave

A working recipe for converting an existing Obsidian-shaped markdown vault into the 5-folder TheWeave convention (`entities/`, `sessions/`, `wiki/`, `LearningLayer/`, `_archive/`), with proper bi-temporal frontmatter on every entity.

Built and validated against a real-world migration: **`~/Documents/TimmyMemory/` (548 Obsidian notes) + `~/.openclaw/agents/timmy/` (250+ agent-home files) → `~/Documents/TimmyMemory-v2/` (663 TheWeave notes, doctor-green, 100% bi-temporal coverage)** on 2026-05-28. The migration ran in under a minute once the rules were tuned.

The script ships at `tools/migrate_obsidian.py`. It is **pragmatic, not a general framework** — adapt the rule tables to your vault. The engine (stub-filter, glob matcher, frontmatter generator, report) is reusable; the rules are vault-specific.

---

## When to use this

You have an existing Obsidian-style vault (or any markdown directory tree) and you want to bring it under TheWeave so the 5-pattern engine can retrieve from it, time-travel through it, and consolidate it. Symptoms that the engine isn't getting much out of your existing layout — easiest to confirm by running `weave-cli doctor --vault <your-vault>` first:

- `entities 0, sessions 0, signals 0` even though the vault has hundreds of notes — the engine can't classify your content because TheWeave's `type:` frontmatter isn't there.
- `Pattern 2 graph: N nodes, ~73%+ isolates` — wikilink density is too low for PPR retrieval to walk usefully.
- Doctor can't find your sessions or LearningLayer folders.

If doctor's verdict is "engine ran fine but nothing's classified," migrate.

---

## What the script does

For each `.md` file in each source directory:

1. **Skip auto-heal stubs** — files with `type: stub` frontmatter, `source: auto-heal`, or body matching the *"auto-generated because referenced but did not exist"* template. These are Obsidian healing-tool artefacts, not knowledge.
2. **Skip Obsidian escaped-dot duplicates** — files like `CORE\.md` sitting alongside `CORE.md`. Filename glitches from rename/aliasing.
3. **Apply the first matching rule** — rule patterns use a glob where `**/` means *any number of directory segments* (so `projects/**/*.md` matches both `projects/foo.md` and `projects/sub/bar.md`). Rules decide:
   - **Destination subdir** under the new vault (`entities/`, `sessions/`, `wiki/...`, `LearningLayer/`, `_archive/`), or `None` to drop the file.
   - **TheWeave `type:`** to stamp on the new frontmatter (`entity`, `session`, `wiki`, `learning-signals`, `agent`, `project`, `person`, `concept`, `decision`, etc.). The doctor's classification reads this field.
   - **Filename strategy**: `preserve_name`, `date_prefixed` (extracts date from frontmatter or filename), `entity_prefix` (kebab-flattens nested paths into `entity-<flat>.md`), `preserve_subpath`, or `rename:<target>` (with optional `{stem}` substitution).
4. **Rewrite frontmatter** — emit `name`, `type`, `valid_from`, `valid_until: null`, `status: current`, plus `origin_path: <source-label>:<rel-path>` for back-reference. Preserves existing `tags` and `source`.
5. **Preserve the body verbatim** — including all `[[wikilinks]]`, headings, tables, etc. The script does not attempt LLM-driven rewrites.
6. **Write to destination** — only when `--apply` is passed.

A catch-all rule at the bottom of every rule list (`**/*.md` → `_archive/unmatched/`) ensures no file is silently lost. If anything lands there, it's a signal that you missed a rule.

---

## The recipe

### 1. Audit the source vault first

```bash
weave-cli doctor --vault ~/Documents/<your-source-vault>
```

Note the warnings. They'll tell you what TheWeave can't currently make of your structure. Especially:

- What `Layout:` did the doctor detect?
- How many notes per `type:`?
- What's the isolate percentage?

### 2. Sample the folder shapes

```bash
VAULT=~/Documents/<your-source-vault>
for d in $(ls "$VAULT"); do
  n=$(find "$VAULT/$d" -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  echo "$d/ — $n files"
done
```

For each non-trivial folder, peek at one or two sample files:

```bash
find "$VAULT/<some-folder>" -name '*.md' | head -2 | while read f; do
  echo "=== $f ==="; head -15 "$f"
done
```

You're looking for:
- **What's the unit?** Is each file a person? A project? A daily log? A reflection?
- **Frontmatter pattern?** Some folders already have `type:`/`tags:`/`date:`. Use those.
- **Stub-shaped files?** Auto-heal output sneaks in everywhere. The is-stub detector catches the common shape; you may need to extend it for your tool.
- **Subdirectories?** `agents/Sonnet/...` is a different shape than `agents/Lucky.md`. The `entity_prefix` strategy flattens; `preserve_subpath` keeps the hierarchy.

### 3. Write the rule table

In `tools/migrate_obsidian.py`, find the rule list (e.g. `TIMMYMEMORY_RULES`). Replace with your vault's rules. Order matters — first match wins. Convention:

```python
Rule("<short label>",
     "<glob pattern from source root>",
     "<destination subdir>",   # or None to drop
     "<TheWeave type to stamp>",  # or None to preserve original
     "<filename strategy>",
     description="<one-liner for the report>"),
```

Recommended rule order:

1. **Specific drops first** — `Rule("plugin output", "TagsRoutes/**/*.md", None, None, "preserve_name")`
2. **Specific renames** — `Rule("user entity", "USER.md", "entities", "person", "rename:entity-user.md")`
3. **Folder-class rules** — `Rule("daily logs", "daily/*.md", "sessions", "session", "date_prefixed")`
4. **Nested folder rules** — `Rule("agents", "agents/**/*.md", "entities", "agent", "entity_prefix")`
5. **Catch-all last** — `Rule("unmatched", "**/*.md", "_archive/unmatched", None, "preserve_subpath")`

### 4. Dry-run + iterate

```bash
python tools/migrate_obsidian.py --dry-run
```

Read the report carefully:

- Per-rule counts — do they match what you expected from the folder sampling?
- Stubs / artefacts skipped — sanity-check the count.
- **Unmatched fallthrough count** — if non-zero, something didn't match a specific rule. Use the rule-samples debug output to see which files fell through, add specific rules above the catch-all, re-run.
- **Frontmatter parse errors** — files with malformed YAML. They're skipped and logged; you'll need to fix the source files manually (usually one bad alias or unquoted colon).

Iterate the rules until the fallthrough is zero or contains only stuff you genuinely want archived.

### 5. Apply

```bash
python tools/migrate_obsidian.py --apply --dest ~/Documents/<your-vault>-v2
```

The script **refuses to overwrite** an existing destination — pick a fresh sibling path (the recommended naming pattern is `<original>-v2/`, mirroring TheWeave's own internal migrations). Production vault stays untouched until you declare cutover.

### 6. Doctor the result

```bash
weave-cli doctor --vault ~/Documents/<your-vault>-v2
```

Compare against the audit from step 1. You should see:

- `entities N, sessions M, signals K` non-zero — the engine now sees your content as structured.
- `Bi-temporal coverage: N/N entities (100%)` — every entity has the bi-temporal triple.
- `Frontmatter parses on all notes`.
- Layout: `flat (seed-vault style)`.

The persistent warning will likely be **PPR graph isolate rate**. Existing vaults are often lightly cross-referenced. The migration preserves whatever wikilinks were there but doesn't add new ones. Address by hand-linking the highest-value entities later, or accept it as a known limitation for v1.

### 7. Hand-write the BOOT file + wiki index

The script can't generate these — they require taste. Mirror the Sonnet starter's `personas/sonnet/SONNET-BOOT.md` and `personas/sonnet/wiki/index.md`, customized for your agent's protocol. Put `<AGENT>-BOOT.md` at the **vault root** (not under any subfolder) so it's the obvious first read.

Required minimum:
- `<AGENT>-BOOT.md` — session-start + session-end protocol, references to canonical entities and wiki notes
- `wiki/index.md` — curated list of the most-important wiki notes, used as part of the session-start protocol

### 8. Wire into Claude Desktop (or your MCP client)

Use TheWeave's `weave-mcp-server` pointed at the new vault path. The standalone `Wire TheWeave to Claude Desktop.command` from the preview-installer bundle works perfectly here — just point it at the new vault when it prompts.

### 9. Cutover discipline

Don't delete the source vault yet. The migration produces a sibling. Run sessions against the new vault for a few real working stretches. When the new vault is clearly comfortable, archive the original (move it out of Obsidian's index — e.g. to `~/Documents/<original>-archive/`) and update any tooling that points at the old path.

---

## Known limitations

- **No LLM-driven wikilink seeding.** PPR isolate rates often stay high after migration because Obsidian users typically rely on tags more than wikilinks. A future version of the tool could optionally run a tag-to-wikilink heuristic or an LLM pass to surface candidate links — not yet implemented.
- **No content rewrites.** The script copies the body verbatim. If your old content has stale frontmatter inside the body, or markdown that uses Obsidian-specific extensions (Dataview, etc.), those land in the new vault unchanged.
- **Frontmatter parse errors silently skipped.** Files with broken YAML are logged but not migrated. You'll need to hand-fix and re-run, or migrate them manually.
- **TOML rule config not yet implemented.** Rules live inline as Python data. For now, fork the script and edit the rule tables; a future version may externalize.
- **Source-vault identity is lost when entities collide.** If two sources have a file claiming to be the user (e.g. `USER.md` from an agent home AND `User Profile.md` from a Claude Memory dir), both will land — you'll need to manually merge or pick one canonical.

---

## A real-world example: TimmyMemory migration

The script ships with `TIMMYMEMORY_RULES` and `IDENTITY_RULES` as worked examples. Per-rule outcomes from the 2026-05-28 run:

| Source class | Files | Destination | TheWeave type |
|---|---:|---|---|
| `daily/` | 32 | `sessions/` | session |
| `wiki/**/` | 132 | `wiki/...` | wiki |
| `projects/**/` | 45 | `entities/entity-project-*.md` | project |
| `agents/**/` | 274 | `entities/entity-agent-*.md` | agent |
| `topics/**/` | 4 | `entities/entity-*.md` | concept |
| `archive/**/` | 24 | `_archive/...` | (passthrough) |
| `_shared/people/**/` | 5 | `entities/entity-*.md` | person |
| `_shared/{facts,decisions}/**/` | 3 | `entities/entity-*.md` | concept/decision |
| `_shared/{CORE,identity,diamond-to-timmy}.md` | 3 | `wiki/*.md` | wiki |
| `_system/**/` | 2 | `_archive/...` | (passthrough) |
| `Claude Memory/*.md` | 6 | `wiki/*.md` | wiki |
| `Sonnet Input/briefs/*.md` | 2 | `sessions/...` | session |
| `~/.openclaw/agents/timmy/{USER,SOUL}.md` | 2 | `entities/entity-{user,timmy}.md` | person/agent |
| `~/.openclaw/agents/timmy/{AGENTS,DREAMS,...}.md` | 9 | `wiki/*.md` | wiki |
| `~/.openclaw/agents/timmy/agent/*.md` | 2 | `_archive/agent-old/` | (passthrough) |
| `~/.openclaw/agents/timmy/brain/lessons/*.md` | 1 | `wiki/lessons/...` | wiki |
| `~/.openclaw/agents/timmy/memory/*.md` | 54 | `sessions/...` | session |
| `~/.openclaw/agents/timmy/memory/dreaming/{deep,rem,light}/*.md` | 69 | `LearningLayer/signals-*.md` | learning-signals |
| TagsRoutes/ + IDENTITY.md template | 4 | (dropped) | — |
| Auto-heal stubs | 11 | (dropped) | — |
| Obsidian escaped-dot artefacts | 23 | (dropped) | — |
| Frontmatter parse errors | 3 | (skipped, logged) | — |

Hand-finishing added 2 files (`TIMMY-BOOT.md`, `wiki/index.md`). Final vault: 663 files, doctor green, 100% bi-temporal.
