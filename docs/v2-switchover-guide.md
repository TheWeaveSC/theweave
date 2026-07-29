# Installing The Weave Core into Claude Desktop

A 5-minute install. By the end you'll have the 5 Weave Core tools (`view`, `create`, `str_replace`, `insert`, `delete`) available inside Claude Desktop, reading and writing a markdown vault of your choice.

---

## Prerequisites

- **macOS** with **Claude Desktop** installed and logged in.
- **Python 3.11 or newer** (`python3 --version` to check; install via Homebrew or the official installer if missing).
- **`git`** (`git --version` to check).
- A **markdown vault directory** — any folder of `.md` files you want Claude Desktop to read and write. If you don't have one yet, just create an empty folder; The Weave will populate it.

---

## 1. Clone the sandbox

```bash
cd ~
git clone https://github.com/TheWeaveSC/theweave.git weave-2.0-sandbox
cd weave-2.0-sandbox
```

## 2. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

`pip install -e .` installs The Weave's dependencies (networkx, mcp, python-frontmatter, click, pydantic, numpy, scipy) and registers the `weave-cli` and `weave-mcp-server` entry-points.

## 3. Smoke-test the engine against the seed vault

```bash
./weave-cli info
./weave-cli demo boot "show me the ACME project"
./weave-cli demo current entity-ACME
./weave-cli demo current entity-ACME --as-of 2026-01-01
```

If those four commands print without errors, the engine is working. The seed vault is a synthetic 15-note demo that ships with the repo; it lets you exercise every pattern without pointing at your real vault yet.

## 4. Wire the MCP server into Claude Desktop

Open Claude Desktop's config file:

```bash
open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

(If the file doesn't exist, create it with `{ "mcpServers": {} }` as starting content.)

Find the `mcpServers` block (or create one) and add the `weave-core` entry. Replace `<YOUR_USERNAME>` with your Mac username (run `whoami` in Terminal if unsure) and `<YOUR_VAULT_PATH>` with the absolute path to the markdown directory you want Claude to read and write:

```json
{
  "mcpServers": {
    "weave-core": {
      "command": "/Users/<YOUR_USERNAME>/weave-2.0-sandbox/.venv/bin/python",
      "args": ["-m", "weave.mcp_server"],
      "env": {
        "WEAVE_VAULT_PATH": "<YOUR_VAULT_PATH>"
      }
    }
  }
}
```

A ready-to-edit version of this snippet lives at `docs/claude-desktop-config.snippet.json` in the repo.

## 5. Restart Claude Desktop

Fully quit Claude Desktop (Cmd-Q), then reopen. MCP servers are loaded at launch — restarting picks up the new entry.

## 6. Verify

In a new Claude conversation, ask something like:

> Use `weave-core/view` to list the root of the vault.

You should see the contents of whichever directory you pointed `WEAVE_VAULT_PATH` at. The 5 tools — `view`, `create`, `str_replace`, `insert`, `delete` — are now available to Claude inside any conversation on this desktop.

---

## Daily use

- **Reading** — Claude can `view` files and directories inside the vault.
- **Writing** — Claude can `create` new files, `str_replace` exact substrings, `insert` lines at any position, and `delete` files or empty directories.
- **Path safety** — all writes are sandboxed to the vault root. Attempts to escape (e.g., `../etc/passwd`) raise `VaultPathError`.

For the Pro engine (PPR boot retrieval, bi-temporal time-travel, sleep-time consolidator, write-time conflict resolver), see `README.md` Section "Five patterns" and the architecture explainer at `docs/architecture.md`.

---

## Switching from MOCK to live Claude (optional, Pro patterns only)

Patterns 4 and 5 (consolidator reflect step + conflict classifier) default to deterministic mock implementations. To upgrade them to real Claude:

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
export WEAVE_CLAUDE_MODEL=claude-sonnet-4-6   # optional override
./weave-cli demo consolidate                  # now uses Claude for reflect
./weave-cli demo write /tmp/foo.md            # now uses Claude for the verdict
```

The selector in `weave/pro/llm.py` picks `anthropic_llm` whenever `ANTHROPIC_API_KEY` is set and falls back to `mock_llm` otherwise. Mock mode is fine for trying everything out; live mode is only needed when you want LLM-quality classification.

---

## Uninstall / rollback

The cleanest possible reversal. No data is at risk:

```bash
# 1. Remove the `weave-core` entry from claude_desktop_config.json
# 2. Restart Claude Desktop
# 3. (Optional) delete the sandbox
rm -rf ~/weave-2.0-sandbox
```

Your vault directory is untouched by this — Claude Desktop just stops being able to read or write it through The Weave.

---

## Troubleshooting

- **"command not found: python3"** — install Python 3.11+ via `brew install python@3.11` or the official installer at python.org.
- **"command not found: git"** — install via `brew install git` or Apple's Xcode Command Line Tools (`xcode-select --install`).
- **MCP server doesn't appear in Claude Desktop after restart** — check the path in the config snippet. `command` must be an absolute path. The venv must exist at that path. Test by running it manually: `/Users/<you>/weave-2.0-sandbox/.venv/bin/python -m weave.mcp_server` (it should print "ERROR: set WEAVE_VAULT_PATH …" and exit — that means the server can launch, it just needs the env var).
- **"ERROR: set WEAVE_VAULT_PATH"** — the `env.WEAVE_VAULT_PATH` line is missing or empty in your config snippet.
- **VaultPathError when Claude tries to read something** — Claude attempted to access a path outside the vault root. Check what it was trying to access; if legitimate, expand `WEAVE_VAULT_PATH` to a higher parent directory.

For anything not covered here, open an issue at https://github.com/TheWeaveSC/theweave/issues.
