# Org Team Engine — arm-on-connect hook patch (ADDITIVE ONLY).
#
# This file is NOT executed by anything in this repo. It is a documented
# patch snippet for the Chairman to apply, by hand, to the LIVE hook at
# ~/.claude/hooks/weave-session-start.sh — a file this repo never touches.
#
# WHAT IT DOES
# ------------
# After the existing hook computes its `directive` string, this block
# shells out to `weave-cli team hydrate` (in-repo templates, no vault
# required) and appends the output to `additionalContext`. This is TEXT
# INJECTION ONLY:
#   - no WeaveCore write
#   - no MCP call
#   - no LLM call
#   - no subprocess that could spawn an agent
# "Reaching weave-core" now also arms the team (roster + loop + routing
# land in context), but zero agents run and zero tokens are spent until a
# human actually assigns a task to a seat.
#
# It degrades exactly like the existing hook already degrades when the
# vault is offline: on ANY failure (venv missing, CLI import error,
# timeout), `team_block` is the empty string and the hook emits exactly
# the same JSON it emits today — no new failure mode is introduced.
#
# HOW TO APPLY
# ------------
# Open ~/.claude/hooks/weave-session-start.sh and, inside
# the `<<'PY' ... PY` heredoc, insert the block below AFTER the existing
# `directive = f"""..."""` assignment and BEFORE the final `print(...)`
# call. Then replace the final print's `"additionalContext": directive`
# with `"additionalContext": additionalContext` (computed below).
#
# The venv python path is hardcoded (matches this hook's existing
# hardcoded /opt/homebrew/bin/python3 style) so it never depends on PATH.
# Replace <path-to-your-weave-repo> with the absolute path of your clone.

import subprocess

WEAVE_SANDBOX_PYTHON = "<path-to-your-weave-repo>/.venv/bin/python"

team_block = ""
try:
    result = subprocess.run(
        [WEAVE_SANDBOX_PYTHON, "-m", "weave", "team", "hydrate", "--source", "templates"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        team_block = result.stdout
except Exception:
    team_block = ""

# Net effect on the final print() call in the live hook:
#   additionalContext = directive + ("\n\n---\n\n" + team_block if team_block.strip() else "")
#   print(json.dumps({
#       "hookSpecificOutput": {
#           "hookEventName": "SessionStart",
#           "additionalContext": additionalContext,
#       },
#       "suppressOutput": True,
#   }))
