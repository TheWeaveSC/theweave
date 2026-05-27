# 🪶 The Weave 2.0 — sandbox prototype

Built overnight while SC slept. Five memory-architecture patterns standing up on a synthetic vault, each runnable from a single CLI. Completely isolated from the real SecondBrain.

**Sandbox location:** `~/weave-2.0-sandbox/`
**Real vault touched:** zero files

---

## Dependencies

| Layer | What | Required? |
|---|---|---|
| Engine runtime | Python ≥ 3.11; deps installed via `pip install -e .` | **Yes** |
| AI ↔ vault | Claude Desktop (or any MCP-aware client) with the `weave-core` server registered | **Yes** |
| Human ↔ vault | A markdown editor. **[Obsidian](https://obsidian.md/)** is recommended because it renders `[[wikilinks]]` and the backlink graph natively, which is most of the v2 UX. The engine works against any directory of `.md` files — Obsidian is not required for AI memory to function. | Recommended |
| Pattern 4/5 live mode | `ANTHROPIC_API_KEY` exported. Without it, both patterns run in deterministic mock mode. | Optional |
| Local LLM (Ollama / Hermes) | Not used by The Weave 2.0 at any layer. | – |

After install, run `./weave-cli doctor` to verify the full stack — engine, vault, environment, and optionally Claude Desktop MCP wiring with `--check-mcp`.

---

## 60-second wake-up tour

```bash
cd ~/weave-2.0-sandbox

# 0 — health check (engine + vault + environment)
./weave-cli doctor --vault /path/to/your/vault --check-mcp

# 1 — what's wired
./weave-cli info

# 2 — Pattern 2: query-driven boot (replaces the static SONNET-BOOT.md)
./weave-cli demo boot "ACME cutover with Marcus"

# 3 — Pattern 3: bi-temporal hop (the GorlyERP-v1.0.7 → v1.2.8 problem, solved)
./weave-cli demo current entity-ACME
./weave-cli demo current entity-ACME --as-of 2026-01-01   # time-travel

# 4 — Pattern 5: write-time conflict resolution
./weave-cli demo write-fixture
./weave-cli demo write /tmp/weave-fixture-new-session.md

# 5 — Pattern 4: sleep-time consolidator (dry-run by default)
./weave-cli demo consolidate --today 2026-05-23
./weave-cli demo consolidate --today 2026-05-23 --apply   # patches entities + backs up to _archive/

# 6 — Pattern 1: launch the MCP server (stdio) for Claude Desktop
./weave-cli mcp   # blocks; Ctrl+C to quit
```

---

## What's wired vs what's stubbed

| Pattern | Implementation | LLM dependency | Production-ready? |
|---|---|---|---|
| **1. Weave Core 5-verb MCP** | Full — `view/create/str_replace/insert/delete` over any vault; path-escape protected | None | ✅ ships as-is |
| **2. PPR boot retrieval** | Full — NetworkX Personalized PageRank, frontmatter-aware wikilink graph, bi-temporal-aware seed resolution | None | ✅ ships as-is |
| **3. Bi-temporal resolver** | Full — `superseded_by` chain walker, `as_of` time travel, current-entity filter | None | ✅ ships as-is |
| **4. Sleep-time consolidator** | Scanning + per-entity activity patching + reflect-bucketing full. Reflect synthesis is mock by default (deterministic keyword bucketing). | Real Claude via `ANTHROPIC_API_KEY` env var (lazy import — install `anthropic` SDK when ready) | 🟡 mock now; one env var to real |
| **5. Write-time conflict resolution** | Full — TF-IDF k-NN candidate search, name-match bypass, superseded-entity redirect, ADD/UPDATE/DELETE/NOOP verdicts. Mock heuristic by default. | Same as above | 🟡 mock now; one env var to real |

All persistence layers use **plain markdown files**. No ChromaDB. No Ollama. No services. The sandbox demonstrates that the substrate (Anthropic 5-verb shape + wikilink graph) carries 80% of the architecture; only the LLM-classification steps need a model.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │   The Weave 2.0 — two-tier design    │
                    └──────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════╗
║  WEAVE CORE  (zero-infra, Claude Desktop / Cowork installable)     ║
║                                                                    ║
║  ┌─────────────────────────────────────────────────────────────┐  ║
║  │  MCP server — 5 verbs over any markdown vault               │  ║
║  │    view  •  create  •  str_replace  •  insert  •  delete    │  ║
║  └─────────────────────────────────────────────────────────────┘  ║
║                              │                                     ║
║                              ▼                                     ║
║  ┌─────────────────────────────────────────────────────────────┐  ║
║  │  Vault (markdown + YAML frontmatter)                        │  ║
║  │    entities/   sessions/   wiki/   LearningLayer/           │  ║
║  └─────────────────────────────────────────────────────────────┘  ║
╚════════════════════════════════════════════════════════════════════╝
                              │
                              ▼ (same vault, richer engine)
╔════════════════════════════════════════════════════════════════════╗
║  WEAVE PRO  (your machine + Hermes/Ollama eventually)              ║
║                                                                    ║
║  Pattern 2 — Query → entity-extract → Personalized PageRank →      ║
║              top-N notes (bi-temporal-aware)                       ║
║                                                                    ║
║  Pattern 3 — Bi-temporal frontmatter (valid_from / valid_until /   ║
║              superseded_by) + chain resolver                       ║
║                                                                    ║
║  Pattern 4 — Sleep-time consolidator:                              ║
║              recent sessions → per-entity activity patch           ║
║              LearningLayer signals → reflect synthesis             ║
║              (dry-run by default; --apply with _archive/ backup)   ║
║                                                                    ║
║  Pattern 5 — Write-time:                                           ║
║              TF-IDF k-NN candidates → LLM (or mock) →              ║
║              ADD / UPDATE / DELETE / NOOP verdict                  ║
║                                                                    ║
║              ┌──────────────┐         ┌─────────────────┐          ║
║              │  mock_llm    │ ◄─────► │  anthropic_llm  │          ║
║              │ (offline)    │  env    │  (live Claude)  │          ║
║              └──────────────┘  var    └─────────────────┘          ║
╚════════════════════════════════════════════════════════════════════╝
```

The two tiers share **one vault**. Different engines on top. Weave Academy learners install only the Core tier (an MCP server in their Claude Desktop config). SC's own setup runs both.

---

## How each pattern closes the gaps we discussed

You said the two gaps were **memory gap** (boot is manual + lossy, no temporal evolution of facts) and **learning-loop gap** (LearningLayer captures observations but they don't reshape behaviour).

| Gap | Pattern that closes it |
|---|---|
| Re-orientation is manual on every new session | **Pattern 2** — boot is query-driven, not pre-baked. Parser bugs become irrelevant because nothing is pre-computed. |
| Wikilinks are flat — no time | **Pattern 3** — `superseded_by` makes time first-class. `entity-ACME` always resolves forward; `--as-of` lets you read historical state. |
| Observations get written but don't loop back | **Pattern 4** — every consolidation cycle pulls recent activity INTO the entity files and runs reflect over LearningLayer. The loop closes. |
| New session notes overwrite or duplicate existing facts | **Pattern 5** — every write goes through k-NN + verdict; the system actively refuses to ADD a duplicate when an UPDATE is correct. |
| Distribution: Weave Academy learners can't bring Ollama with them | **Pattern 1** — 5 verbs, no infra. Anthropic memory tool shape. One MCP entry in `claude_desktop_config.json` and they're in. |

---

## Switching from MOCK to live Claude

Patterns 4 and 5 default to deterministic mock implementations. To go live:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
export WEAVE_CLAUDE_MODEL=claude-sonnet-4-6   # optional override
./weave-cli demo consolidate                  # now uses Claude for the reflect step
./weave-cli demo write /tmp/foo.md            # now uses Claude for the verdict
```

The `weave/pro/llm.py` selector picks `anthropic_llm` whenever `ANTHROPIC_API_KEY` is set, falls back to `mock_llm` otherwise. Code paths are identical; only the classifier swaps.

---

## Installing the Core MCP into Claude Desktop

Copy `docs/claude-desktop-config.snippet.json` into your existing `~/Library/Application Support/Claude/claude_desktop_config.json` under `mcpServers`. Restart Claude Desktop. The 5 verbs become available as `weave-core/view`, `weave-core/create`, etc.

For the Weave Academy install path, the same snippet is the entire integration — no Ollama, no Hermes, no DB.

---

## Files

```
weave-2.0-sandbox/
├── weave/                     # Python package
│   ├── vault.py               # rooted vault; wikilink scan over body + frontmatter
│   ├── core.py                # Pattern 1 — 5-verb memory tool
│   ├── mcp_server.py          # FastMCP server exposing the 5 verbs
│   ├── cli.py                 # `weave demo …` entry-point
│   ├── __main__.py            # python -m weave
│   └── pro/
│       ├── bitemporal.py      # Pattern 3
│       ├── ppr.py             # Pattern 2
│       ├── similarity.py      # TF-IDF k-NN (stdlib only)
│       ├── conflict.py        # Pattern 5
│       ├── consolidator.py    # Pattern 4
│       ├── mock_llm.py        # offline classifiers
│       ├── anthropic_llm.py   # live Claude classifiers
│       └── llm.py             # selector by env var
├── seed-vault/                # synthetic 15-note vault for the demo
├── docs/
│   ├── architecture.md
│   └── claude-desktop-config.snippet.json
├── weave-cli                  # bash convenience wrapper
├── BUILD-LOG.md               # what was done overnight
└── README.md                  # this file
```

---

## Caveats (full honesty, since you're tired)

- **Python 3.14 was used** for the sandbox. LD #4 pins 3.11 because of ChromaDB. The sandbox doesn't use ChromaDB so 3.14 was fine. If you graft Patterns 2–5 into cortex-mem later, switch back to `~/.local/bin/python3.11`.
- **Consolidator's reflect step is mock-quality** without the API key. The bucketing-by-keywords is honest stub — not a substitute for a real synthesis pass.
- **TF-IDF in the conflict resolver is short-doc-fragile.** Short candidate notes get low similarity scores even when they're conceptually identical; the name-match bypass covers most of this. Real embeddings (nomic-embed-text via Ollama) would be the production path.
- **PPR is run-time over the whole graph**, not cached. Fine for vaults <1k notes; pre-compute and cache for larger vaults.
- **MCP server has been smoke-tested via the Python API** (tools list, schema construction). Full end-to-end with Claude Desktop requires you to register the config snippet on your side — I deliberately did not modify your `claude_desktop_config.json`.
- **The seed vault uses fictional entity names** (ACME / FOO / Marcus) so nothing looks like a stale copy of real Weave data if anyone glances at this directory.

See `BUILD-LOG.md` for the chronological build log.
