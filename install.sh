#!/usr/bin/env bash
# One-click installer wrapper: `./install.sh --vault ~/my-vault`
#
# Thin pass-through to `weave-cli init`. Mirrors the ./weave-cli wrapper's
# discipline of resolving the sandbox's own venv rather than relying on
# whatever's on PATH.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec "$DIR/.venv/bin/python" -m weave init "$@"
