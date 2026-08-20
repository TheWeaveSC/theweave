"""Write-time conflict resolution — Pattern 5.

Before writing a new note into the vault, retrieve k-NN existing notes via
TF-IDF, ask the LLM (or mock) ADD/UPDATE/DELETE/NOOP, and return a Proposal
the caller can either auto-apply (with backup) or surface to the user.

v1 write-gate addition: a DETERMINISTIC pre-filter runs over the k-NN
candidates BEFORE any LLM classify. It flags each candidate
{hard_conflict | likely_duplicate | unrelated} from frontmatter + cosine
similarity alone. NOOP/unrelated outcomes skip the LLM call entirely;
hard_conflict goes to the LLM only when a real one is configured (and the
caller allows it), otherwise the deterministic finding is surfaced in the
Proposal rationale. This keeps the MCP write gate off the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import frontmatter

from ..vault import Vault
from .similarity import TFIDFIndex
from .llm import get_llm, is_mock

# Candidate flags (pre-filter verdicts, per candidate).
HARD_CONFLICT = "hard_conflict"
LIKELY_DUPLICATE = "likely_duplicate"
UNRELATED = "unrelated"

# Cosine thresholds over the existing TF-IDF machinery.
# - >= NOOP_THRESHOLD with zero contradicting keys: the note already exists
#   in near-identical form -> deterministic NOOP, no LLM.
# - >= DUP_THRESHOLD: near-duplicate content; contradicting frontmatter
#   makes it a hard conflict, otherwise a likely duplicate.
# - >= RELATED_THRESHOLD: related enough that contradicting frontmatter
#   keys count as a hard conflict. Below it, shared-but-differing keys are
#   noise (every note disagrees with every other note on `date`-like keys),
#   so the candidate is flagged unrelated.
NOOP_THRESHOLD = 0.95
DUP_THRESHOLD = 0.75
RELATED_THRESHOLD = 0.35

# Frontmatter keys excluded from contradiction detection: bookkeeping /
# lifecycle values that legitimately differ between two notes about the same
# subject. Flagging `date` or `valid_from` mismatches would mark the entire
# vault as conflicting with itself.
VOLATILE_KEYS: frozenset[str] = frozenset({
    "date", "created", "updated", "modified", "version",
    "valid_from", "valid_until", "superseded_by", "supersedes",
    "type", "tags", "aliases",
})


@dataclass
class CandidateFinding:
    """Deterministic pre-filter verdict for ONE k-NN candidate."""
    rel_path: str
    score: float
    flag: str                                   # hard_conflict | likely_duplicate | unrelated
    conflicting_keys: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    verdict: str            # ADD | UPDATE | DELETE | NOOP
    target_path: str | None
    rationale: str
    candidates: list[tuple[str, float]]   # (rel_path, score)
    is_mock: bool
    findings: list[CandidateFinding] = field(default_factory=list)
    llm_called: bool = False


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_value(value) -> str:
    """Comparable scalar form: str(), stripped, lowercased. Lists/dicts are
    normalized element-wise so ['A', 'B'] == ['b', 'a'] is still a difference
    but casing/whitespace is not."""
    if isinstance(value, (list, tuple, set)):
        return "[" + ", ".join(sorted(_normalize_value(v) for v in value)) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{_normalize_key(str(k))}: {_normalize_value(v)}"
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        ) + "}"
    return str(value).strip().lower()


def _comparable_frontmatter(metadata: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in metadata.items():
        nk = _normalize_key(str(k))
        if nk in VOLATILE_KEYS or v is None:
            continue
        out[nk] = _normalize_value(v)
    return out


def parse_new_note_frontmatter(new_note_content: str) -> dict:
    """Frontmatter of the CANDIDATE note (full text incl. any --- block).
    Malformed YAML degrades to {} — the pre-filter must never crash a write."""
    try:
        return dict(frontmatter.loads(new_note_content).metadata)
    except Exception:
        return {}


def prefilter(
    new_note_content: str,
    candidates: list[tuple[str, float, dict]],   # (rel_path, score, frontmatter)
) -> list[CandidateFinding]:
    """Deterministic conflict pre-filter (Item 2). No LLM, no network.

    Per candidate:
      - overlapping normalized frontmatter keys with differing values, on a
        candidate at least RELATED_THRESHOLD similar -> hard_conflict
        (+ offending keys);
      - near-duplicate content (>= DUP_THRESHOLD) without contradicting
        keys -> likely_duplicate;
      - everything else -> unrelated.
    """
    new_fm = _comparable_frontmatter(parse_new_note_frontmatter(new_note_content))
    findings: list[CandidateFinding] = []
    for rel_path, score, metadata in candidates:
        cand_fm = _comparable_frontmatter(metadata if isinstance(metadata, dict) else {})
        diff_keys = sorted(
            k for k in (new_fm.keys() & cand_fm.keys())
            if new_fm[k] != cand_fm[k]
        )
        if diff_keys and score >= RELATED_THRESHOLD:
            flag = HARD_CONFLICT
        elif score >= DUP_THRESHOLD:
            flag = LIKELY_DUPLICATE
            diff_keys = []
        else:
            flag = UNRELATED
            diff_keys = []
        findings.append(CandidateFinding(rel_path, score, flag, diff_keys))
    return findings


class ConflictResolver:
    """k-NN + deterministic pre-filter + (optionally) LLM-classified write proposal."""

    def __init__(self, vault: Vault, *, top_k: int = 5):
        self.vault = vault
        self.top_k = top_k
        self.index = TFIDFIndex(vault).build()

    def propose(
        self,
        *,
        new_note_name: str,
        new_note_content: str,
        exclude: set[str] | None = None,
        allow_llm: bool = True,
    ) -> Proposal:
        """Propose ADD/UPDATE/DELETE/NOOP for a candidate note.

        `exclude`: rel_paths to drop from the k-NN candidates (a write gate
        excludes the target note itself so it never "conflicts" with its own
        prior version).
        `allow_llm=False`: deterministic-only mode — never calls the LLM
        module at all (not even the mock); verdicts come from the pre-filter.
        The MCP write gate runs in this mode so a write never blocks on a
        network call.
        """
        matches = self.index.query(
            new_note_content + " " + new_note_name,
            top_k=self.top_k,
            exclude=exclude,
        )
        candidates = [
            (m.note.rel_path, m.score, m.note.metadata)
            for m in matches
        ]
        findings = prefilter(new_note_content, candidates)
        pairs = [(p, s) for p, s, _ in candidates]

        hard = [f for f in findings if f.flag == HARD_CONFLICT]
        dups = [f for f in findings if f.flag == LIKELY_DUPLICATE]

        # Deterministic NOOP: a near-identical note already exists and nothing
        # contradicts. Skip the LLM entirely.
        if dups and dups[0].score >= NOOP_THRESHOLD and not hard:
            top = dups[0]
            return Proposal(
                verdict="NOOP",
                target_path=top.rel_path,
                rationale=(f"[prefilter] near-identical to `{top.rel_path}` "
                           f"(sim {top.score:.2f}) with no contradicting "
                           f"frontmatter; nothing to write."),
                candidates=pairs, is_mock=is_mock(), findings=findings,
            )

        # All-unrelated (or no candidates at all): plain ADD, skip the LLM.
        if not hard and not dups:
            top_score = findings[0].score if findings else 0.0
            return Proposal(
                verdict="ADD",
                target_path=None,
                rationale=(f"[prefilter] no related or conflicting notes "
                           f"(top sim {top_score:.2f}); treating as a new ADD."),
                candidates=pairs, is_mock=is_mock(), findings=findings,
            )

        # Something conflicts or duplicates. Real LLM only if configured AND
        # the caller allows it; otherwise surface the deterministic finding.
        if allow_llm and not is_mock():
            llm = get_llm()
            result = llm.classify_write(
                new_note_name=new_note_name,
                new_note_content=new_note_content,
                candidates=candidates,
            )
            rationale = result.rationale
            if hard:
                rationale += " " + _hard_conflict_summary(hard)
            return Proposal(
                verdict=result.verdict,
                target_path=result.target_path,
                rationale=rationale,
                candidates=pairs, is_mock=result.is_mock,
                findings=findings, llm_called=True,
            )

        # Deterministic-only outcome (no LLM configured, or gate mode).
        top = hard[0] if hard else dups[0]
        rationale = (
            f"[prefilter] {_hard_conflict_summary(hard)} Proposing UPDATE of "
            f"`{top.rel_path}` — verify the merge."
            if hard else
            f"[prefilter] near-duplicate of `{top.rel_path}` "
            f"(sim {top.score:.2f}); proposing UPDATE rather than a duplicate ADD."
        )
        return Proposal(
            verdict="UPDATE",
            target_path=top.rel_path,
            rationale=rationale,
            candidates=pairs, is_mock=True, findings=findings,
        )


def _hard_conflict_summary(hard: list[CandidateFinding]) -> str:
    parts = [f"`{f.rel_path}` on {', '.join(f.conflicting_keys)}" for f in hard]
    return f"Hard frontmatter conflict with {'; '.join(parts)}."
