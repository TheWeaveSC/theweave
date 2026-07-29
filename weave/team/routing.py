"""route(seat, task_difficulty) -> Tier.

Pure function, no I/O — exhaustively unit-testable. Precedence:
  1. explicit task_difficulty override (always wins)
  2. cue-word match in the task text
  3. seat.default_tier
  4. engine default (STANDARD), if seat is None and nothing else resolved
"""

from __future__ import annotations

from .models import DEFAULT_TIER, Seat, Tier

MECHANICAL_CUES: tuple[str, ...] = (
    "single-string edit", "edit", "grep", "fixture", "rename", "dedupe", "fetch",
)
HARD_CUES: tuple[str, ...] = (
    "adversarial", "gate", "judge", "design", "synthesis", "reproduce",
)


def _cue_tier(task_text: str) -> Tier | None:
    if not task_text:
        return None
    text = task_text.lower()
    # Check HARD cues first: hard-tier language ("adversarial verify",
    # "design review") should not be masked by a coincidental mechanical
    # substring elsewhere in the same task description.
    for cue in HARD_CUES:
        if cue in text:
            return Tier.HARD
    for cue in MECHANICAL_CUES:
        if cue in text:
            return Tier.MECHANICAL
    return None


def route(seat: Seat | None, task_difficulty: str | Tier | None = None,
          task_text: str = "") -> Tier:
    """Resolve the tier for a seat/task.

    - seat: the Seat whose default_tier applies if nothing else wins.
    - task_difficulty: explicit override — str ("hard"/"standard"/"mechanical")
      or a Tier. Always wins if provided.
    - task_text: free text scanned for cue words if no explicit override.
    """
    if task_difficulty is not None:
        if isinstance(task_difficulty, Tier):
            return task_difficulty
        return Tier.from_str(str(task_difficulty))

    cued = _cue_tier(task_text)
    if cued is not None:
        return cued

    if seat is not None:
        return seat.default_tier

    return DEFAULT_TIER


__all__ = ["route", "MECHANICAL_CUES", "HARD_CUES"]
