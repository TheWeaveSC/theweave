# Changelog

All notable changes to TheWeave are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-08-20

### Added
- **Lane firewall (fail-closed).** Notes are routed into retrieval lanes via a repo-root `lane_map.yaml` (explicit rulings > filename globs > dir prefixes > LearningLayer vocabulary > default); recall, dense search, and PPR seeding are all lane-filtered, hub files are never embedded or seeded, and quarantined bridge files are never retrievable in any lane. Bridge detection is fail-closed (H1–H4): `cortex rebuild` REFUSES to build when an unruled note matches both bridge-vocab lists, the lane-config hash is stamped into the cortex manifest and stale caches are refused at read time, quarantined files are dropped as graph nodes entirely, and seeds are lane-filtered before PageRank on both the main and degraded paths.
- **Cortex w2.4 read-path hardening.** Malformed-note survivability: one broken note degrades that note only — the read path reports the fault instead of dying (or silently hiding it) — and quarantine exclusion is enforced at every retrieval seam.
- **`weave lint`** — vault lint verb (`weave-cli lint`, `--paths` for machine-readable output).
- **Deterministic conflict pre-filter** — TF-IDF similarity pre-filter in front of conflict verdicts, so unrelated writes skip the LLM entirely.
- **Advisory write gate on MCP write verbs** — `create` / `str_replace` / `insert` / `delete` get an advisory conflict proposal appended to their result (fail-open: gate errors never block the write; disable with `WEAVE_WRITE_GATE=0`).
- **Windows support (beta).** Platform-aware Claude Desktop config-path resolution (macOS / `%APPDATA%` / XDG), platform-native cortex cache locations, `install-weave.ps1` PowerShell installer, and a clear macOS-only guard on the launchd nightly installer. Implemented and code-reviewed, not yet field-tested on Windows — feedback invited via issues.
- New engine test suites: lane firewall, bridge quarantine, seed lane purity, read-path faults, write gate, lint, conflict pre-filter, hydrate, cortex, bench.
- **`tools/migrate_obsidian.py`** — Obsidian-to-TheWeave migration tool. Reads one or more source directories (an Obsidian-style vault plus optional auxiliary directories like an agent's identity home), applies a rule table of glob-pattern → destination-subdir + TheWeave type + filename strategy, filters auto-heal stubs and Obsidian escaped-dot duplicates, rewrites frontmatter with bi-temporal triple + `origin_path` back-reference, preserves wikilinks and body verbatim. `--dry-run` mode prints a per-rule report without writing. Validated end-to-end against an existing 548-note Obsidian vault plus a 250+-file agent home — produced a 663-note TheWeave-shaped vault, doctor green, 100% bi-temporal coverage.
- **[`docs/migrate-from-obsidian.md`](docs/migrate-from-obsidian.md)** — reusable migration recipe. When to migrate, audit → sample → rules → dry-run → apply → doctor → hand-finish → cutover. Includes a worked example with per-rule outcomes from a real migration.

### Fixed
- **`mcp>=1.0,<2` dependency pin** — mcp 2.0.0 removed `mcp.server.fastmcp`, breaking every fresh install; pinned to the 1.x line.

## [0.3.0] — 2026-05-28

### Added
- **Persona-as-vault primitive.** New top-level [`personas/`](personas/) directory holding fork-and-edit starter vaults. Persona is reframed as a vault you point TheWeave at — same primitive as factual memory, different loading discipline (always-loaded vs retrieved-on-demand).
- **`personas/sonnet/`** starter — a terse, audit-discipline Claude collaborator persona with voice, working-style, and relationship scaffolding pre-wired. Validates 100% bi-temporal coverage via `weave-cli doctor`.
- **`personas/sonnet/SONNET-BOOT.md`** — deterministic session-start protocol (list LearningLayer → list entities → skim wiki index) and session-end protocol (entity updates, signal, session note). Turns the starter from a demo into a working persona.
- **`personas/sonnet/wiki/entity-discipline.md`** — operating manual for the persona-as-vault pattern: allocation rule (entity vs wiki vs session vs LearningLayer), when to create vs extend entities, naming conventions, required frontmatter, when to ask vs just write, wikilink discipline.
- **`install-weave.sh`** — zero-clone installer. Fetches the release tarball from GitHub's public archive endpoint (no auth required), creates a venv at `$WEAVE_HOME/venv/`, installs the package, optionally symlinks `weave-cli` into `~/.local/bin/`, and runs `weave-cli doctor` as the success signal. Overridable via `WEAVE_VERSION`, `WEAVE_HOME`, `PYTHON`.
- [`docs/release-checklist.md`](docs/release-checklist.md) — the workflow to cut a tagged release that the installer can fetch.
- Full public-facing README rewrite: tagline-first hero, "Bring your own persona" section, positioning vs vector-DB memory layers, dedicated Quickstart, Install, and Limitations sections.
- Badges in README: license, Python version, current version, MCP compatibility.

### Changed
- `pyproject.toml`: `personas/` excluded from packaged distribution (it's reference data, not engine code).

## [0.2.0] — 2026-05-27

### Added
- `weave-cli doctor` install-verification gate with four check groups (Engine, Vault, Environment, MCP). Exit code equals the number of failures. Supports `--vault <path>` and `--check-mcp`.
- Doctor sentinels for two recurring failure modes: hardcoded vault-path string literals (the v0.1.1 regression class) and v1's zero-edges graph-indexing regression.
- `docs/architecture.md` and a refreshed Dependencies section in the README.

## [0.1.1] — 2026-05-27

### Fixed
- **Pattern 4 (sleep-time consolidator):** removed hardcoded `startswith("sessions/")` assumption that only matched the seed-vault flat layout. The consolidator now resolves vault structure dynamically and works on canonical `<VaultName>Vault/...` layouts. Pre-fix: 0 sessions scanned on real vaults. Post-fix: full scan with correct per-entity activity patching.

## [0.1.0] — 2026-05-27

### Added
- Initial release. Five-pattern memory architecture over a markdown vault:
  - **Pattern 1 — Weave Core MCP:** 5-verb (`view` / `create` / `str_replace` / `insert` / `delete`) memory tool with vault-path-escape protection. FastMCP server.
  - **Pattern 2 — PPR boot retriever:** Personalized PageRank with frontmatter-aware wikilink graph and bi-temporal-aware seed resolution. NetworkX-backed.
  - **Pattern 3 — Bi-temporal resolver:** `superseded_by` chain walker, `as_of` time-travel, current-entity filter.
  - **Pattern 4 — Sleep-time consolidator:** session scanning, per-entity activity patching, LearningLayer reflect synthesis. Dry-run by default; `--apply` opt-in with `_archive/` backups.
  - **Pattern 5 — Write-time conflict resolver:** TF-IDF k-NN candidate search with mock-or-live LLM verdicts (ADD/UPDATE/DELETE/NOOP). Name-match bypass + superseded-redirect built in.
- Synthetic 15-note seed vault (fictional ACME / FOO / Marcus entities) for demos.
- `weave-cli` shell wrapper exposing `info`, `demo`, `mcp` commands.
- Anthropic Claude live-mode path for Patterns 4 and 5 via `ANTHROPIC_API_KEY`; deterministic mock mode by default.
- Apache 2.0 license.

[Unreleased]: https://github.com/TheWeaveSC/theweave/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.4.0
[0.3.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.3.0
[0.2.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.2.0
[0.1.1]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.1.1
[0.1.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.1.0
