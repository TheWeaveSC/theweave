"""Runtime selector: real Claude if ANTHROPIC_API_KEY set, else MOCK."""

from __future__ import annotations

import os


def get_llm():
    """Return the active LLM module (mock_llm or anthropic_llm)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from . import anthropic_llm as impl
        return impl
    from . import mock_llm as impl
    return impl


def is_mock() -> bool:
    return not bool(os.environ.get("ANTHROPIC_API_KEY"))
