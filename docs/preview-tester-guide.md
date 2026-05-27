# TheWeave — Preview tester guide

You're testing a private preview of TheWeave before it's released publicly. This guide walks you through three things: **install**, **picking a persona**, and **pointing it at a vault**. Plain steps, no shortcuts assumed.

Estimated time: 10–15 minutes.

---

## What you'll need

| | |
|---|---|
| **Operating system** | macOS or Linux. Windows works via WSL but isn't covered here. |
| **Python 3.11 or newer** | Check with `python3 --version`. If you don't have it, install from [python.org](https://www.python.org/downloads/) or via Homebrew (`brew install python@3.11`). |
| **Two files from SC** | `theweave-preview.tar.gz` (the source) and `install-weave.sh` (the installer). Save both to your Downloads folder. |
| **Claude Desktop** *(optional)* | If you want to actually wire TheWeave to a live Claude session. Skip if you just want to verify the engine works. |

---

## Step 1 — Install

Open Terminal (macOS: ⌘+Space, type "Terminal"). Run these commands one at a time.

### 1a. Verify Python

```bash
python3 --version
```

You should see something like `Python 3.11.x` or higher. If you see an older version or "command not found", install Python 3.11+ first.

### 1b. Run the installer

```bash
cd ~/Downloads
WEAVE_TARBALL=~/Downloads/theweave-preview.tar.gz bash install-weave.sh
```

The installer will:

1. Check for Python, curl, and tar
2. Create a directory at `~/theweave/`
3. Set up a Python virtual environment
4. Install TheWeave + dependencies into it
5. Run `weave-cli doctor` to verify everything works

**What success looks like:** the last line says `TheWeave v0.x.x installed.` and `weave-cli doctor` passes with green checkmarks.

**If something fails:**
- The installer will stop at the failing step and tell you what went wrong
- Most likely cause: Python version too old, or you already have `~/theweave/` from a previous attempt (the installer will offer to remove it)
- Send the full output to SC if you can't figure it out

---

## Step 2 — Confirm it's working

In the same Terminal:

```bash
~/theweave/venv/bin/weave-cli doctor
```

You should see something like:

```
🪶 Weave 2.0 Doctor

[Engine]
  ✓ Python 3.11.x (≥3.11 required)
  ✓ Dependencies importable
  ✓ CLI + MCP entry points importable

[Vault]
  ✓ Vault root resolves: ...
  ✓ 18 notes total — entities 6, sessions 7, signals 1, other 4
  ✓ Bi-temporal coverage: 6/6 entities (100%)

All checks passed.
```

If `weave-cli` isn't found, try the full path: `~/theweave/venv/bin/weave-cli doctor`. The installer tries to put it on your `PATH` automatically, but on some setups it can't.

---

## Step 3 — Pick a persona

A **persona** in TheWeave is the assistant's identity — voice, working style, the way it talks to you. It's not a system prompt or a setting. It's a folder of markdown files. You can read every one. You can edit every one.

TheWeave ships with a starter persona called **Sonnet** — a terse, audit-discipline Claude collaborator. To use it, copy it to a vault location on your machine:

```bash
cp -R ~/theweave/personas/sonnet ~/my-vault
```

This gives you a fresh vault at `~/my-vault/`. Look inside:

```bash
ls ~/my-vault
# entities/  sessions/  wiki/  LearningLayer/  _archive/  README.md
```

The five folders are the vault's structure. Open any `.md` file with a text editor (TextEdit, VS Code, BBEdit — anything) and you can read what makes Sonnet, Sonnet:

- **`entities/entity-sonnet.md`** — who the assistant is
- **`entities/entity-user.md`** — who you are *(this is the file you edit next)*
- **`wiki/voice.md`** — how Sonnet sounds
- **`wiki/working-style.md`** — how Sonnet collaborates

### Personalize it

Open `~/my-vault/entities/entity-user.md` in a text editor and replace the placeholder content with your actual name, role, and preferences. The file has prompts showing you what to fill in. This is the only file you *need* to edit; everything else is optional.

When you're done, save the file. The next time TheWeave loads the vault, it'll use the new content.

---

## Step 4 — Verify your new vault loads

```bash
~/theweave/venv/bin/weave-cli doctor --vault ~/my-vault
```

You should see another all-green doctor report, this time pointed at your personal vault. The note count will be 11 (the contents of the Sonnet starter).

If you see warnings (yellow ⚠), the engine still works but something in the vault isn't ideal. Send the doctor output to SC — that's exactly the kind of feedback we want from this preview.

---

## Step 5 *(optional)* — Connect to Claude Desktop

This is the step that makes TheWeave actually do something useful in conversations with Claude.

### 5a. Find Claude Desktop's config file

On macOS:

```bash
ls "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

If the file doesn't exist, open Claude Desktop and go to Settings → Developer to enable MCP, which creates it.

### 5b. Add TheWeave's MCP server entry

Open the config file in a text editor. There's a sample entry to copy at `~/theweave/docs/claude-desktop-config.snippet.json`. Merge it into the `mcpServers` section of your config, replacing the vault path with **your** vault: `~/my-vault`.

### 5c. Restart Claude Desktop

Fully quit (⌘+Q) and reopen. In a new conversation, you should see `weave-core` listed in the available tools.

### 5d. Test it

In Claude Desktop, ask Claude:

> "Read entity-sonnet.md from the vault and tell me what kind of assistant Sonnet is supposed to be."

If Claude responds with content from `wiki/voice.md`-style language (terse, audit-discipline, recommend-don't-enumerate), the wiring works.

---

## What we'd love feedback on

Three specific questions. Reply to SC with whatever you have — even one-sentence answers help.

1. **Did the install work end-to-end?** Which step (if any) was unclear or broke?
2. **Does the persona-as-vault idea land?** When you read about "your assistant's identity is a folder you can edit," does that feel like the headline feature, or like a side feature?
3. **What would you want next?** More starter personas? Better docs? A specific use case the docs don't cover?

Anything else — typos, awkward phrasing, "I expected X but got Y" — is also useful. This preview exists to find these things before the public release.

---

## If you hit a wall

- Check the doctor output: `~/theweave/venv/bin/weave-cli doctor` will diagnose most install problems
- Read `~/theweave/README.md` for the full project context
- Reach out to SC directly with the Terminal output of whatever broke

Thanks for testing.
