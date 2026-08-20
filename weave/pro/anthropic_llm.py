"""Real LLM path — Claude calls via the Anthropic API.

Used when ANTHROPIC_API_KEY env var is set. Exposes the same function
signatures as weave.pro.mock_llm so the consumer code can swap at runtime.

Sandbox DOES NOT pre-install the anthropic SDK. Import is lazy so the module
loads cleanly even without the package present; calling a function without
the SDK installed raises a clear error directing the user to `pip install anthropic`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Literal

from .mock_llm import ClassifyResult, Verdict

_MODEL = os.environ.get("WEAVE_CLAUDE_MODEL", "claude-sonnet-4-6")


def _client():
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK not installed. Run `pip install anthropic` to enable "
            "real LLM mode, or unset ANTHROPIC_API_KEY to fall back to MOCK."
        ) from e
    return anthropic.Anthropic()


_CLASSIFY_PROMPT = """You are evaluating whether a new vault note should be ADDed,
UPDATEd (merged into an existing note), DELETE an existing superseded note, or NOOP.

NEW NOTE NAME: {new_name}

NEW NOTE CONTENT:
{new_content}

EXISTING CANDIDATE NOTES (top similarity matches):
{candidates_block}

Respond with a single JSON object:
{{"verdict": "ADD"|"UPDATE"|"DELETE"|"NOOP", "target_path": "<rel path or null>", "rationale": "<one sentence>"}}
"""


def classify_write(
    *,
    new_note_name: str,
    new_note_content: str,
    candidates: list[tuple[str, float, dict]],
) -> ClassifyResult:
    client = _client()
    cand_block = "\n".join(
        f"- path={p} score={s:.3f} frontmatter={json.dumps(fm, default=str)}"
        for p, s, fm in candidates
    ) or "(none)"
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": _CLASSIFY_PROMPT.format(
                new_name=new_note_name,
                new_content=new_note_content[:4000],
                candidates_block=cand_block,
            )
        }],
    )
    text = "".join(block.text for block in msg.content if hasattr(block, "text"))
    parsed = _extract_json(text)
    return ClassifyResult(
        verdict=parsed.get("verdict", "ADD"),
        target_path=parsed.get("target_path"),
        rationale=parsed.get("rationale", "(no rationale)"),
        is_mock=False,
    )


_REFLECT_PROMPT = """You are doing a reflect-pass over raw LearningLayer signals.
Cluster them into 3-5 higher-order behavioural themes. Be terse.

SIGNALS:
{signals_block}

Respond with markdown — short headings + bullets. No preamble.
"""


def reflect_signals(signals: list[str]) -> str:
    if not signals:
        return "(no signals to reflect on)"
    client = _client()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": _REFLECT_PROMPT.format(
                signals_block="\n".join(f"- {s}" for s in signals)
            )
        }],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))


def _extract_json(text: str) -> dict:
    """Find the first JSON object in a free-form response."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
