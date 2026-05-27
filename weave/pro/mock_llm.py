"""Deterministic offline fallbacks for LLM-touching patterns.

Used when ANTHROPIC_API_KEY is unset. Keeps the sandbox runnable end-to-end
without any network or API dependency. Clearly labelled as MOCK in all
outputs so SC isn't fooled into thinking these are model-quality decisions.

Replace with weave.pro.anthropic_llm at runtime when an API key is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["ADD", "UPDATE", "DELETE", "NOOP"]


@dataclass
class ClassifyResult:
    verdict: Verdict
    target_path: str | None     # which existing note to update (for UPDATE/DELETE)
    rationale: str              # human-readable
    is_mock: bool = True


def classify_write(
    *,
    new_note_name: str,
    new_note_content: str,
    candidates: list[tuple[str, float, dict]],  # (rel_path, score, frontmatter)
) -> ClassifyResult:
    """Decide whether a new note should ADD / UPDATE existing / DELETE old / NOOP.

    Mock heuristic:
      - if top candidate score >= 0.75 and shares a name root → UPDATE that one
      - elif top candidate has `superseded_by` set → propose DELETE on the candidate
      - elif top candidate score >= 0.55 → UPDATE
      - else → ADD
    """
    if not candidates:
        return ClassifyResult(
            verdict="ADD",
            target_path=None,
            rationale="[MOCK] No similar existing notes; treating as a new addition.",
        )

    # Exact-name-match bypass: if any candidate's stem matches the new name, it's an UPDATE
    for path, score, fm in candidates:
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        if stem == new_note_name:
            if fm.get("superseded_by"):
                return ClassifyResult(
                    verdict="UPDATE",
                    target_path=fm.get("superseded_by") if isinstance(fm.get("superseded_by"), str) else path,
                    rationale=(
                        f"[MOCK] Exact name match with `{stem}`, but it is superseded; "
                        f"redirecting UPDATE to its current version."
                    ),
                )
            return ClassifyResult(
                verdict="UPDATE",
                target_path=path,
                rationale=f"[MOCK] Exact name match with existing `{stem}` (sim {score:.2f}); proposing UPDATE.",
            )

    top_path, top_score, top_fm = candidates[0]
    top_stem = top_path.rsplit("/", 1)[-1].removesuffix(".md")
    share_root = _share_name_root(new_note_name, top_stem)

    if top_fm.get("superseded_by"):
        return ClassifyResult(
            verdict="DELETE",
            target_path=top_path,
            rationale=(
                f"[MOCK] Top match `{top_stem}` is already marked superseded "
                f"(superseded_by={top_fm.get('superseded_by')}); proposing DELETE."
            ),
        )
    if top_score >= 0.75 and share_root:
        return ClassifyResult(
            verdict="UPDATE",
            target_path=top_path,
            rationale=(
                f"[MOCK] High similarity ({top_score:.2f}) + shared name root with "
                f"`{top_stem}`; proposing UPDATE rather than a duplicate ADD."
            ),
        )
    if top_score >= 0.55:
        return ClassifyResult(
            verdict="UPDATE",
            target_path=top_path,
            rationale=(
                f"[MOCK] Moderate similarity ({top_score:.2f}) with `{top_stem}`; "
                f"proposing UPDATE — please verify the merge."
            ),
        )
    return ClassifyResult(
        verdict="ADD",
        target_path=None,
        rationale=(
            f"[MOCK] Top similarity only {top_score:.2f}; treating as a new ADD."
        ),
    )


def reflect_signals(signals: list[str]) -> str:
    """Synthesize raw signals into higher-order patterns.

    Mock heuristic: cluster signals by leading bullet/heading and emit a
    template summary. Marks output as MOCK so SC isn't fooled.
    """
    if not signals:
        return "[MOCK] No signals to reflect on."

    # Simple keyword bucketing
    buckets: dict[str, list[str]] = {
        "communication": [],
        "working preferences": [],
        "failure modes": [],
        "other": [],
    }
    for sig in signals:
        low = sig.lower()
        if any(k in low for k in ("communication", "phrasing", "reply", "tone")):
            buckets["communication"].append(sig)
        elif any(k in low for k in ("prefer", "preference", "wants", "likes", "expects")):
            buckets["working preferences"].append(sig)
        elif any(k in low for k in ("fail", "bug", "broken", "stale", "error")):
            buckets["failure modes"].append(sig)
        else:
            buckets["other"].append(sig)

    out = ["[MOCK] Reflect-pass synthesis (deterministic stub — not model-quality)\n"]
    for bucket, items in buckets.items():
        if not items:
            continue
        out.append(f"### {bucket.title()} ({len(items)} signal(s))")
        for item in items:
            out.append(f"- {item}")
        out.append("")
    return "\n".join(out)


def _share_name_root(a: str, b: str) -> bool:
    """Heuristic: do these two note names share the same entity root?"""
    a_root = re.sub(r"-v\d.*$", "", a.lower())
    b_root = re.sub(r"-v\d.*$", "", b.lower())
    return a_root == b_root or a_root.startswith(b_root) or b_root.startswith(a_root)
