# Changelog

All notable changes to TheWeave are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Persona-as-vault primitive.** New top-level [`personas/`](personas/) directory holding fork-and-edit starter vaults. Persona is reframed as a vault you point TheWeave at — same primitive as factual memory, different loading discipline (always-loaded vs retrieved-on-demand).
- **`personas/sonnet/`** starter — a terse, audit-discipline Claude collaborator persona with voice, working-style, and relationship scaffolding pre-wired. Validates 100% bi-temporal coverage via `weave-cli doctor`.
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

[Unreleased]: https://github.com/TheWeaveSC/theweave/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.2.0
[0.1.1]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.1.1
[0.1.0]: https://github.com/TheWeaveSC/theweave/releases/tag/v0.1.0
