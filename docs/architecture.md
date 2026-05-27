# The Weave 2.0 — architecture

A two-tier memory system, both tiers running off the same markdown vault.

---

## Substrate

A plain directory of markdown notes with YAML frontmatter. That is the only required infrastructure. Notes link to each other with Obsidian-style `[[wikilinks]]`, which form a directed graph used by Pattern 2.

A note can be of any type — common conventions in this sandbox:

| Folder | Frontmatter `type` | Examples |
|---|---|---|
| `entities/` | `project`, `person`, `stakeholder`, `research-project` | the things you orient around |
| `sessions/` | `session` | dated work logs, link to entities via `touches:` |
| `LearningLayer/` | `learning-signals` | domain-agnostic observations (per LD #13) |
| `wiki/` | `index` | lean index nodes (LD #1) |
| `_archive/` | — | backups + consolidation reports |

---

## Bi-temporal schema

Entity notes carry time-aware frontmatter:

```yaml
---
name: entity-ACME-v1.2.8
type: project
version: v1.2.8
valid_from: 2026-03-15
valid_until: null            # null = currently valid
supersedes: "[[entity-ACME]]"
status: current
---
```

The prior version carries the inverse:

```yaml
---
name: entity-ACME
version: v1.0.7
valid_from: 2025-11-01
valid_until: 2026-03-15
superseded_by: "[[entity-ACME-v1.2.8]]"
status: superseded
---
```

This is **bi-temporal in spirit, not in full Graphiti** sense — no `t_created` / `t_ingested` tracking. The sandbox shows that the minimum useful subset (just `valid_from` / `valid_until` / `superseded_by`) closes the staleness gap without a graph DB.

---

## Tier 1 — Weave Core (Pattern 1)

`weave/core.py` exposes the Anthropic memory-tool shape directly over a vault:

```
view(path, view_range?)       — read file or list dir
create(path, content)         — create/overwrite
str_replace(path, old, new)   — exact 1-occurrence replace
insert(path, line, content)   — insert before line N
delete(path)                  — delete file or empty dir
```

`weave/mcp_server.py` wraps these as MCP tools using FastMCP. The server takes `WEAVE_VAULT_PATH` from env and exposes the 5 tools over stdio. Claude Desktop / Cowork installs by registering this server in `claude_desktop_config.json`.

All path arguments are sandboxed: any attempt to escape the vault root raises `VaultPathError`. The sandbox includes a smoke test (`view('../etc/passwd')` is blocked).

---

## Tier 2 — Weave Pro

### Pattern 2 — PPR boot retrieval

```
query string
  └─ extract_seeds()              # token-match against known entity names
       └─ resolve through superseded_by chain (Pattern 3)
            └─ Personalized PageRank seeded on resolved targets
                 └─ top-N notes (superseded entities filtered out)
```

`weave/pro/ppr.py` builds a `networkx.DiGraph` once at startup; nodes are note names, edges are wikilinks discovered in both body and frontmatter. PPR scoring uses the standard `nx.pagerank(personalization=…)` with `alpha=0.85`. Result formatting is markdown — the "boot file" is now a thing you generate per query, not pre-bake.

### Pattern 3 — Bi-temporal resolver

`weave/pro/bitemporal.py` walks `superseded_by` links starting from a given name. Optional `as_of=date(…)` parameter stops the walk once it encounters a `valid_from > as_of`, giving time-travel reads.

### Pattern 4 — Sleep-time consolidator

`weave/pro/consolidator.py` does three things in sequence:

1. **Scan**: walk sessions whose dates fall within `window_days`.
2. **Patch**: for each entity touched by ≥1 recent session, generate a `## Recent activity` block to append/replace in that entity file.
3. **Reflect**: pull all `learning-signals` files, extract bullet lines, run them through the LLM's `reflect_signals()` for a higher-order synthesis.

Output is a single markdown consolidation report. Defaults to dry-run (writes the report only). `--apply` patches the entity files, with a per-file backup to `_archive/<entity>-YYYY-MM-DD-HHMM.md`.

The "patch" generation in step 2 is currently deterministic (lists the touching sessions with date + headline). The reflect step in step 3 is delegated to the LLM module (mock by default).

### Pattern 5 — Write-time conflict resolution

`weave/pro/conflict.py` runs before any cortex-mem-style write:

1. **k-NN**: TF-IDF index over the vault returns top-N candidate notes by similarity to the proposed write.
2. **Classify**: the LLM module returns one of {ADD, UPDATE, DELETE, NOOP} with a target path and rationale.
3. **Caller decides**: the proposal is returned, not auto-executed. Caller policy determines whether to apply or surface to the user.

Mock heuristic (offline):
- Exact name match with existing note → `UPDATE` (redirected to current version if the match is superseded).
- Top similarity ≥ 0.55 → `UPDATE`.
- Otherwise → `ADD`.

Real Claude path is in `weave/pro/anthropic_llm.py` (same signature; lazy imports the `anthropic` SDK).

---

## Why this earns its keep

Compared to cortex-mem today:

- **No parser** for the boot file. Parser bugs become irrelevant because the boot is a query-time computation, not a session-end write.
- **No silent stale links.** `superseded_by` is explicit; the resolver enforces it; PPR doesn't seed on dead versions.
- **No reflection gap.** The consolidator's reflect step is where LD #13 signals turn into themes that influence behaviour.
- **No "did the writer overwrite my note?" anxiety.** Pattern 5 makes the verdict visible and reversible.

Compared to the GitHub state-of-the-art it borrows from:

- **vs Mem0**: same write-time-classify spirit, kept in markdown.
- **vs Graphiti**: same bi-temporal idea, ~1% of the infra cost.
- **vs Letta**: sleep-time consolidator is the lightweight version of Letta's sleep-time agent.
- **vs HippoRAG**: same PPR retrieval, on a wikilink graph instead of a knowledge graph.
- **vs A-MEM**: neighbour updates happen in the consolidator, batched nightly instead of on every write.
- **vs Anthropic memory tool**: the Core tier IS the Anthropic memory tool, with Pro layered cleanly on top.
