"""Write-time conflict resolution — Pattern 5.

Before writing a new note into the vault, retrieve k-NN existing notes via
TF-IDF, ask the LLM (or mock) ADD/UPDATE/DELETE/NOOP, and return a Proposal
the caller can either auto-apply (with backup) or surface to the user.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..vault import Vault
from .similarity import TFIDFIndex
from .llm import get_llm, is_mock


@dataclass
class Proposal:
    verdict: str            # ADD | UPDATE | DELETE | NOOP
    target_path: str | None
    rationale: str
    candidates: list[tuple[str, float]]   # (rel_path, score)
    is_mock: bool


class ConflictResolver:
    """k-NN + LLM-classified write proposal."""

    def __init__(self, vault: Vault, *, top_k: int = 5):
        self.vault = vault
        self.top_k = top_k
        self.index = TFIDFIndex(vault).build()

    def propose(self, *, new_note_name: str, new_note_content: str) -> Proposal:
        # Find similar existing notes; exclude any path matching the new note's stem
        matches = self.index.query(new_note_content + " " + new_note_name, top_k=self.top_k)
        candidates = [
            (m.note.rel_path, m.score, m.note.metadata)
            for m in matches
        ]
        llm = get_llm()
        result = llm.classify_write(
            new_note_name=new_note_name,
            new_note_content=new_note_content,
            candidates=candidates,
        )
        return Proposal(
            verdict=result.verdict,
            target_path=result.target_path,
            rationale=result.rationale,
            candidates=[(p, s) for p, s, _ in candidates],
            is_mock=result.is_mock,
        )
