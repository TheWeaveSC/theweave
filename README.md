# TheWeave

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](CHANGELOG.md)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

**Claude memory you can `cat`, grep, and git.**

A markdown-native memory architecture for Claude and any MCP-aware agent. Your assistant's memory lives as plain `.md` files in a directory you own — inspectable in your text editor, versionable in git, portable across machines — not in an opaque vector database somewhere else.

Five composable patterns sit on top of the same vault:

1. **Weave Core MCP** — 5-verb memory tool over any markdown directory
2. **PPR boot retriever** — query-driven Personalized PageRank, not pre-baked dumps
3. **Bi-temporal resolver** — facts have `valid_from` / `superseded_by`; time-travel queries built in
4. **Sleep-time consolidator** — recent activity gets patched back into entity files; reflect synthesis runs over the learning log
5. **Write-time conflict resolver** — k-NN + LLM verdict refuses to ADD a duplicate when an UPDATE is correct

The substrate is just markdown and YAML frontmatter. No services, no embeddings DB, no Ollama. The 5-verb tool ships zero-infra; the richer patterns layer on top of the same files.

---

## Quickstart

```bash
git clone https://github.com/TheWeaveSC/theweave.git ~/theweave
cd ~/theweave
pip install -e .

# verify the install end-to-end
weave-cli doctor

# try the included demo vault
weave-cli demo boot "ACME cutover with Marcus"
weave-cli demo current entity-ACME --as-of 2026-01-01   # time-travel
weave-cli demo consolidate --today 2026-05-23           # dry-run
```

A healthy install looks like:

```
🪶 Weave 2.0 Doctor

[Engine]
  ✓ Python 3.11.15 (≥3.11 required)
  ✓ Dependencies importable
      mcp 1.27.1, networkx 3.6.1, frontmatter 1.3.0, click 8.4.1, ...
  ✓ CLI + MCP entry points importable
  ℹ theweave 0.2.0

[Vault]
  ✓ Vault root resolves: ~/theweave/seed-vault
  ✓ Layout: flat (seed-vault style)
  ✓ 18 notes total — entities 6, sessions 7, signals 1, other 4
  ✓ Frontmatter parses on all notes
  ✓ Pattern 4 will scan 7 session(s)
  ✓ Pattern 2 graph: 18 nodes, 71 edges, 0 isolates (0%)
  ✓ Bi-temporal coverage: 6/6 entities (100%)

[Environment]
  ✓ Obsidian.app detected in /Applications/
  ℹ ANTHROPIC_API_KEY not set — Pattern 4/5 will run in mock mode

All checks passed.
```

Requires Python ≥ 3.11. For a zero-clone install path (no GitHub auth required), see [Install](#install).

---

## Bring your own persona

TheWeave is vault-native. Your assistant's *identity* — voice, working style, the relationship you've built — is itself just markdown in the vault. Persona memories load on every session; factual memories get retrieved on demand. Same primitive, same files, different loading discipline.

That means a persona is just a starter vault you can fork:

```bash
# clone a starter vault and verify the engine sees it
cp -R personas/sonnet ~/my-vault
weave-cli doctor --vault ~/my-vault --check-mcp
$EDITOR ~/my-vault/entities/entity-user.md   # personalize the user identity
```

Starter vaults shipped in this repo:

- **[`seed-vault/`](seed-vault/)** — neutral fictional starter (ACME / FOO entities). Best for kicking the tires on the five patterns.
- **[`personas/sonnet/`](personas/sonnet/)** — a starter built around a terse, audit-discipline Claude collaborator. Voice, working-style, and relationship scaffolding pre-wired. See [`personas/sonnet/README.md`](personas/sonnet/README.md) for the layout and fork instructions.

Or skip the starter and point TheWeave at any existing markdown directory — Obsidian, your notes repo, dotfiles. The engine adapts to whatever layout you have.

---

## What this is (and isn't)

|  | TheWeave | Vector-DB memory layers |
|---|---|---|
| **Storage** | Plain `.md` files in your filesystem | Vendor DB / Pinecone / pgvector |
| **Inspection** | `cat`, `grep`, `rg`, your text editor | API query or admin UI |
| **Versioning** | `git diff`, `git log`, `git blame` | Snapshot/export tools |
| **Schema** | Open YAML frontmatter | Vendor DB schema |
| **Failure mode** | A bad markdown file you can edit by hand | A bad row you have to query out |
| **Vendor lock-in** | None — it's a folder | Migration tool required |

TheWeave is **not** a chat-memory bolt-on. It's the memory layer for Claude when you want the data on your machine, in your filesystem, in a format you can read.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │       TheWeave — two-tier design     │
                    └──────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════╗
║  WEAVE CORE  (zero-infra, drop-in MCP server)                      ║
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
║  WEAVE PRO  (Python engine on your machine)                        ║
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

Both tiers share **one vault**. Core ships zero-infra (an MCP entry in `claude_desktop_config.json` and you're in). Pro adds the richer engine without changing the data format.

---

## Pattern status

| # | Pattern | Implementation | LLM dependency |
|---|---|---|---|
| 1 | **Weave Core MCP** | Stable — 5 verbs, path-escape protected | None |
| 2 | **PPR boot retrieval** | Stable — NetworkX, frontmatter-aware wikilinks, bi-temporal seed resolution | None |
| 3 | **Bi-temporal resolver** | Stable — `superseded_by` walker, `as_of` time-travel | None |
| 4 | **Sleep-time consolidator** | Stable scan + patch. Reflect synthesis uses mock heuristic by default; live Claude with `ANTHROPIC_API_KEY` | Optional |
| 5 | **Write-time conflict resolver** | Stable TF-IDF + verdict pipeline. Mock classifier by default; live Claude with `ANTHROPIC_API_KEY` | Optional |

All persistence is plain markdown. No ChromaDB, no Ollama, no services. The 5-verb substrate carries ~80% of the architecture; only the classifier steps in Patterns 4 and 5 need an LLM.

---

## Install

### Editable install (current path)

```bash
git clone https://github.com/TheWeaveSC/theweave.git ~/theweave
cd ~/theweave
pip install -e .
weave-cli doctor
```

### Zero-clone install (recommended for learners)

```bash
curl -sSL https://github.com/TheWeaveSC/theweave/releases/latest/download/install-weave.sh | bash
```

Downloads the tagged release tarball, sets up a Python venv at `~/theweave/venv/`, installs the package, and symlinks `weave-cli` into `~/.local/bin/` if it's on your PATH. Runs `weave-cli doctor` as the success signal. No GitHub authentication required — the tarball is fetched from the public releases endpoint.

Overridable via env vars: `WEAVE_VERSION`, `WEAVE_HOME`, `PYTHON`. See [`install-weave.sh`](install-weave.sh).

### MCP integration with Claude Desktop

Copy `docs/claude-desktop-config.snippet.json` into your `~/Library/Application Support/Claude/claude_desktop_config.json` under `mcpServers`. Restart Claude Desktop. The 5 verbs become available as `weave-core/view`, `weave-core/create`, etc.

---

## Live Claude mode (Patterns 4 & 5)

Patterns 4 and 5 default to deterministic mock implementations. To go live:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
export WEAVE_CLAUDE_MODEL=claude-sonnet-4-6   # optional
weave-cli demo consolidate                    # reflect step now uses Claude
weave-cli demo write /tmp/foo.md              # verdict now uses Claude
```

The `weave/pro/llm.py` selector picks `anthropic_llm` whenever `ANTHROPIC_API_KEY` is set, falling back to `mock_llm` otherwise. Code paths are identical; only the classifier swaps.

---

## Dependencies

| Layer | What | Required? |
|---|---|---|
| Engine runtime | Python ≥ 3.11; `pip install -e .` installs the rest | **Yes** |
| AI ↔ vault | Claude Desktop, [Cowork](https://cowork.anthropic.com/), or any MCP client with `weave-core` registered | **Yes** |
| Human ↔ vault | Any markdown editor. [Obsidian](https://obsidian.md/) is recommended for the native wikilink + backlink-graph UX, but not required. | Recommended |
| Patterns 4 & 5 live mode | `ANTHROPIC_API_KEY` exported | Optional |

After install, `weave-cli doctor` verifies the full stack — engine, vault, environment, and optionally Claude Desktop MCP wiring with `--check-mcp`.

---

## Limitations

Honest list of what's rough:

- **TF-IDF in the conflict resolver is short-doc-fragile.** Short candidate notes get low similarity scores even when conceptually identical. The name-match bypass covers most of this; real embeddings (e.g., `nomic-embed-text`) would be the production path.
- **PPR runs over the whole graph per query**, not cached. Fine for vaults under ~1,000 notes; pre-compute and cache for larger ones.
- **Consolidator's mock reflect step is keyword-bucketing.** Honest stub, not a substitute for the live-Claude reflect pass.
- **Live LLM mode is Claude only.** No OpenAI / Gemini / Ollama backends — open for contribution.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — deeper technical write-up
- [`docs/v2-switchover-guide.md`](docs/v2-switchover-guide.md) — migrating from v1
- [`CHANGELOG.md`](CHANGELOG.md) — release history

---

## License

[Apache License 2.0](LICENSE).
