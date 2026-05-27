#!/usr/bin/env bash
#
# TheWeave installer — fetches a tagged release from GitHub, sets up a venv,
# installs the package, runs the doctor as the success signal.
#
# Usage:
#   curl -sSL https://github.com/TheWeaveSC/theweave/releases/latest/download/install-weave.sh | bash
#   # or, with overrides:
#   WEAVE_VERSION=0.2.0 WEAVE_HOME=~/theweave bash install-weave.sh
#
# No GitHub authentication required. Tarball is fetched from the public
# releases endpoint.

set -euo pipefail

WEAVE_VERSION="${WEAVE_VERSION:-0.2.0}"
WEAVE_HOME="${WEAVE_HOME:-$HOME/theweave}"
WEAVE_REPO="${WEAVE_REPO:-TheWeaveSC/theweave}"
PYTHON="${PYTHON:-}"

# ── colors ──────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_RESET=$'\033[0m'
else
  C_DIM=""; C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_RESET=""
fi
info()  { printf "%s\n" "$1"; }
ok()    { printf "  ${C_GREEN}✓${C_RESET} %s\n" "$1"; }
warn()  { printf "  ${C_YELLOW}⚠${C_RESET} %s\n" "$1"; }
fail()  { printf "  ${C_RED}✗${C_RESET} %s\n" "$1" >&2; exit 1; }

# ── preflight ───────────────────────────────────────────────────────────
info ""
info "${C_BOLD}TheWeave installer${C_RESET} — v${WEAVE_VERSION}"
info ""
info "[Preflight]"

# Resolve a Python ≥3.11
if [ -z "$PYTHON" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")
      case "$version" in
        3.11|3.12|3.13|3.14) PYTHON="$candidate"; break ;;
      esac
    fi
  done
fi
[ -n "$PYTHON" ] || fail "Python ≥3.11 not found. Install Python 3.11+ and retry."
ok "Python: $PYTHON ($("$PYTHON" --version))"

# curl required
command -v curl >/dev/null 2>&1 || fail "curl is required."
ok "curl: $(command -v curl)"

# tar required
command -v tar >/dev/null 2>&1 || fail "tar is required."
ok "tar: $(command -v tar)"

# ── target dir ──────────────────────────────────────────────────────────
info ""
info "[Target]"
if [ -d "$WEAVE_HOME" ]; then
  if [ -t 0 ]; then
    warn "$WEAVE_HOME already exists."
    read -r -p "    Remove and reinstall? [y/N] " response
    case "$response" in
      [yY]|[yY][eE][sS]) rm -rf "$WEAVE_HOME" ;;
      *) fail "Aborted — keep existing install or set WEAVE_HOME to a different path." ;;
    esac
  else
    fail "$WEAVE_HOME already exists. Remove it, or set WEAVE_HOME=<other-path>."
  fi
fi
mkdir -p "$WEAVE_HOME"
ok "WEAVE_HOME: $WEAVE_HOME"

# ── download + extract ──────────────────────────────────────────────────
info ""
info "[Download]"
TARBALL_URL="https://github.com/${WEAVE_REPO}/archive/refs/tags/v${WEAVE_VERSION}.tar.gz"
info "  ${C_DIM}${TARBALL_URL}${C_RESET}"
if ! curl -sSL --fail "$TARBALL_URL" | tar -xz -C "$WEAVE_HOME" --strip-components=1; then
  fail "Download failed. Check that release v${WEAVE_VERSION} exists at github.com/${WEAVE_REPO}/releases."
fi
ok "Extracted source to $WEAVE_HOME"

# ── venv + install ──────────────────────────────────────────────────────
info ""
info "[Install]"
"$PYTHON" -m venv "$WEAVE_HOME/venv"
ok "Created venv at $WEAVE_HOME/venv"

# shellcheck source=/dev/null
"$WEAVE_HOME/venv/bin/pip" install --quiet --upgrade pip
"$WEAVE_HOME/venv/bin/pip" install --quiet "$WEAVE_HOME"
ok "Installed theweave + dependencies into venv"

# ── PATH convenience ────────────────────────────────────────────────────
LOCAL_BIN="$HOME/.local/bin"
if [ -d "$LOCAL_BIN" ] && case ":$PATH:" in *":$LOCAL_BIN:"*) true;; *) false;; esac; then
  ln -sf "$WEAVE_HOME/venv/bin/weave-cli" "$LOCAL_BIN/weave-cli"
  ok "Symlinked weave-cli into $LOCAL_BIN (on PATH)"
  WEAVE_CLI="weave-cli"
else
  warn "$LOCAL_BIN not on PATH — invoke via full path:"
  warn "    $WEAVE_HOME/venv/bin/weave-cli"
  WEAVE_CLI="$WEAVE_HOME/venv/bin/weave-cli"
fi

# ── verify ──────────────────────────────────────────────────────────────
info ""
info "[Verify]"
if "$WEAVE_HOME/venv/bin/weave-cli" doctor >/dev/null 2>&1; then
  ok "weave-cli doctor: passed"
else
  warn "weave-cli doctor reported issues — run \`$WEAVE_CLI doctor\` to see details"
fi

# ── done ────────────────────────────────────────────────────────────────
info ""
info "${C_GREEN}${C_BOLD}TheWeave v${WEAVE_VERSION} installed.${C_RESET}"
info ""
info "Next:"
info "  1. ${C_BOLD}Pick a starter vault${C_RESET} (or point at your own):"
info "       cp -R $WEAVE_HOME/personas/sonnet ~/my-vault"
info "       $WEAVE_CLI doctor --vault ~/my-vault"
info ""
info "  2. ${C_BOLD}Register the MCP server${C_RESET} with Claude Desktop:"
info "       see $WEAVE_HOME/docs/claude-desktop-config.snippet.json"
info ""
info "  3. ${C_BOLD}Read the docs${C_RESET}:"
info "       $WEAVE_HOME/README.md"
info "       $WEAVE_HOME/docs/architecture.md"
info ""
