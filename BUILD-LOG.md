# The Weave 2.0 — Build Log

Sonnet building while SC slept. Final log on completion.

---

## Build phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 0 | Sandbox scaffold + venv + deps | ✅ Done | Python 3.14.5 (LD #4 caveat noted), networkx/mcp/frontmatter/click/pydantic + numpy/scipy |
| 1 | Synthetic seed vault | ✅ Done | 15 notes: 6 entities (incl. ACME v1.0.7 → v1.2.8 supersession), 7 sessions, 1 LearningLayer, 1 wiki index |
| 2 | Weave Core MCP (Pattern 1) | ✅ Done | 5 verbs, path-escape safety verified, FastMCP server live |
| 3 | PPR boot retriever (Pattern 2) | ✅ Done | Frontmatter-aware wikilinks, token-level seed extraction, bi-temporal-aware seed resolution |
| 4 | Bi-temporal resolver (Pattern 3) | ✅ Done | `superseded_by` chain, `as_of` time-travel, current-entity filter |
| 5 | Write-time conflict resolver (Pattern 5) | ✅ Done | TF-IDF k-NN + mock classifier (name-match bypass + superseded redirect); real-LLM path stubbed in anthropic_llm.py |
| 6 | Sleep-time consolidator (Pattern 4) | ✅ Done | dry-run by default + --apply with _archive backups; reflect step routes to mock or real LLM |
| 7 | CLI demo wrapper + README + docs | ✅ Done | `./weave-cli info|demo boot|demo current|demo write|demo consolidate|mcp` |

---

## Plan-mode interlude

Mid-build, SC engaged plan mode (likely after seeing the numpy import error from networkx). Wrote `~/.claude/plans/tidy-jingling-metcalfe.md` with the remaining-work map and key decision recommendations:

- **D1** (numpy/scipy): installed (chose option a in plan)
- **D2** (conflict resolver LLM dependency): mock-by-default with env-var switch to live Claude
- **D3** (consolidator side effects): dry-run by default, --apply opt-in with backups
- **D4** (Claude Desktop integration): config snippet shipped in `docs/`
- **D5** (mock-LLM placement): single `weave/pro/mock_llm.py` + `anthropic_llm.py` + `llm.py` selector

SC approved the plan and engaged auto mode. Resumed and finished.

---

## Decisions made overnight

1. **Python 3.14 for the sandbox.** LD #4 pins 3.11 because of ChromaDB. The sandbox uses no ChromaDB (pure-Python alternatives), so 3.14 was fine. When grafting onto cortex-mem later, switch back to `~/.local/bin/python3.11`.
2. **Sandbox at `~/weave-2.0-sandbox/`.** Top-level home, outside iCloud SecondBrain. Zero risk to real vault.
3. **Mock-LLM mode is default.** Setting `ANTHROPIC_API_KEY` switches Patterns 4+5 to real Claude. Lazy import of `anthropic` SDK — no install required for mock-only use.
4. **Fictional entity names in the seed vault.** ACME / FOO / Marcus so nothing reads like stale Weave-real data.
5. **Bi-temporal schema:** `valid_from`, `valid_until`, `superseded_by`, `supersedes` (optional bidir). Minimum useful Graphiti-ish subset without a graph DB.
6. **Cortex-mem stays untouched.** Parallel prototype, not a replacement.
7. **Consolidator side effects gated.** Default dry-run; `--apply` flag required, and every patched file gets a backup in `_archive/`.

---

## Bugs found + fixed during build

- `wikilinks()` was only scanning body; frontmatter `touches:` wikilinks were not edges. **Fixed** by extending to recursively walk metadata strings.
- PPR entity extraction used only the full stripped name; "thesis" alone missed `entity-FOO-thesis`. **Fixed** with token-level matching + stopword filter.
- PPR seed-deduplication after bi-temporal hop: `entity-ACME` and `entity-ACME-v1.2.8` both matched and both resolved to v1.2.8, producing duplicate seed in the report. **Fixed** with post-resolution dedup.
- Mock classifier missed UPDATE for near-duplicate entity rewrites because TF-IDF on short docs gives low similarity. **Fixed** by adding name-exact-match bypass + superseded-target redirect.
- Modern networkx routes `pagerank` through scipy; `numpy` + `scipy` not installed initially. **Fixed** with `pip install numpy scipy` after plan approval.

---

## Smoke tests run (all passing)

- Weave Core 5 verbs: view (file + dir + line-range), create, str_replace (1-occurrence enforcement), insert (line 0 prepend), delete
- Vault path safety: `../etc/passwd`, `/etc/passwd`, `../../Library/SecondBrain` — all blocked
- MCP server: builds, exposes 5 tools, FastMCP tool list verified
- Bi-temporal: `entity-ACME` → `entity-ACME-v1.2.8` (current), `as_of 2026-01-01` correctly stays on v1.0.7
- PPR: 4 different queries — seeded ones correctly extract, cold-boot fallback to global PageRank works
- Conflict resolver: ADD (low similarity), UPDATE (name match), DELETE-redirect (superseded target), correct in all 4 test cases
- Consolidator: dry-run report writes to `_archive/`, --apply patches entities + creates per-entity backups, restored seed vault to pre-apply state after testing

---

## Files written

```
~/weave-2.0-sandbox/
├── README.md
├── BUILD-LOG.md  (this file)
├── weave-cli  (executable wrapper)
├── weave/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── core.py
│   ├── mcp_server.py
│   ├── vault.py
│   └── pro/
│       ├── __init__.py
│       ├── anthropic_llm.py
│       ├── bitemporal.py
│       ├── conflict.py
│       ├── consolidator.py
│       ├── llm.py
│       ├── mock_llm.py
│       ├── ppr.py
│       └── similarity.py
├── seed-vault/
│   ├── entities/ (6 .md files)
│   ├── sessions/ (7 .md files)
│   ├── LearningLayer/signals-2026-05.md
│   ├── wiki/index.md
│   └── _archive/ (empty; populated when consolidator runs)
└── docs/
    ├── architecture.md
    └── claude-desktop-config.snippet.json
```

Final state: clean. Seed vault in pre-demo state. Empty `_archive/`. Ready for SC to explore.
