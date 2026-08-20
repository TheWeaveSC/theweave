"""LongMemEval-style retrieval benchmark harness — Cortex W0 (measure first).

Measures what the CURRENT read path can recall from a vault, so every later
cortex claim (W2 hybrid retrieval, W5 before/after) is a number, not an
assertion. MECHANISM only: probes live in fixture files (repo: synthetic
bench-vault; local: a private probe file outside the repo — never private
vault content in-repo).

Probe file (YAML list):

    - id: sh-01
      category: single-hop        # single-hop | associative | temporal |
                                  # knowledge-update | abstention
      query: "What port does the ACME replica listen on?"
      gold: [session-2026-04-02-acme-migration-review]   # note NAMES
      # abstention probes have gold: []

Scoring (retrieval-level, per probe, at cutoff k):
    hit@k     — any gold note in the top-k
    recall@k  — |gold ∩ top-k| / |gold|
    rr        — 1/rank of the first gold note (0 if none)
    abstention — pass iff the retriever ABSTAINS (no confident seeds/hits);
                 recall metrics do not apply

Retrievers (the W0 baseline set; W2 adds `hybrid`):
    ppr      — PPRBoot: entity-seed extraction -> Personalized PageRank
    keyword  — distinct query-token hit count over raw note text (the floor:
               what naive grep-and-view gets you)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..vault import Note, Vault
from .ppr import PPRBoot, _STOPWORDS

CATEGORIES = ("single-hop", "associative", "temporal", "knowledge-update", "abstention")


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


@dataclass
class Probe:
    id: str
    category: str
    query: str
    gold: list[str]
    # lane firewall: which recall lane the probe queries. Optional in the YAML
    # (default operational); only the hybrid retriever is lane-aware — the
    # W0 baselines (ppr/keyword) are lane-blind by design.
    lane: str = "operational"

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError(f"probe {self.id}: unknown category {self.category!r}")
        if self.category == "abstention" and self.gold:
            raise ValueError(f"probe {self.id}: abstention probes must have empty gold")
        if self.category != "abstention" and not self.gold:
            raise ValueError(f"probe {self.id}: non-abstention probe needs gold notes")
        if self.lane == "ops":  # probe-author shorthand
            self.lane = "operational"
        from .dense import LANES
        if self.lane not in LANES:
            raise ValueError(f"probe {self.id}: unknown lane {self.lane!r}")


def load_probes(path: str | Path) -> list[Probe]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"probe file {path}: expected a YAML list")
    probes = [Probe(id=str(p["id"]), category=p["category"],
                    query=p["query"], gold=list(p.get("gold") or []),
                    lane=p.get("lane", "operational")) for p in raw]
    ids = [p.id for p in probes]
    if len(ids) != len(set(ids)):
        raise ValueError(f"probe file {path}: duplicate probe ids")
    return probes


def validate_gold(probes: list[Probe], vault: Vault) -> list[str]:
    """Every gold note must exist in the vault — a typo'd gold silently
    deflates the baseline and poisons every later comparison."""
    names = {n.name for n in vault.iter_notes()}
    missing = []
    for p in probes:
        for g in p.gold:
            if g not in names:
                missing.append(f"{p.id}: gold note {g!r} not in vault")
    return missing


# ---------------------------------------------------------------------------
# Retrievers — each returns (ranked note names, abstained flag)
# ---------------------------------------------------------------------------


class PPRRetriever:
    """The current boot retriever: entity seeds -> Personalized PageRank."""

    name = "ppr"

    def __init__(self, vault: Vault):
        self._boot = PPRBoot(vault)
        self._boot.build()

    def retrieve(self, query: str, k: int,
                 lane: str = "operational") -> tuple[list[str], bool]:
        # lane accepted but IGNORED: the W0 boot baseline is lane-blind.
        result = self._boot.run(query, top_n=k)
        abstained = not result.seeds  # cold boot = no entity matched = abstain
        return [n.name for n, _ in result.ranked], abstained


class KeywordRetriever:
    """Floor baseline: rank notes by distinct query-token presence in raw text
    (name hits weighted up). Approximates naive grep-and-view."""

    name = "keyword"

    def __init__(self, vault: Vault):
        self._notes: list[Note] = sorted(vault.iter_notes(), key=lambda n: n.rel_path)

    def retrieve(self, query: str, k: int,
                 lane: str = "operational") -> tuple[list[str], bool]:
        # lane accepted but IGNORED: the keyword floor is lane-blind.
        tokens = {t for t in re.findall(r"[a-z0-9]{3,}", query.lower())
                  if t not in _STOPWORDS}
        scored: list[tuple[float, str]] = []
        for n in self._notes:
            text = n.raw_text.lower()
            name = n.name.lower()
            score = 0.0
            for t in tokens:
                if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text):
                    score += 1.0
                if t in name:
                    score += 0.5
            if score > 0:
                scored.append((score, n.name))
        scored.sort(key=lambda s: (-s[0], s[1]))
        # Abstain when nothing matches at least two distinct tokens (a single
        # stray word match is noise, not evidence the vault knows the answer).
        confident = [name for score, name in scored if score >= 2.0]
        return [name for _, name in scored[:k]], not confident


class HybridRetriever:
    """W2 cortex read path: dense seeds PPR (requires a built cortex)."""

    name = "hybrid"

    def __init__(self, vault: Vault, embedder=None):
        from .cortex import cortex_exists
        if not cortex_exists(vault):
            raise RuntimeError(
                "hybrid retriever needs a built cortex — run `weave cortex rebuild`")
        self._vault = vault
        self._embedder = embedder

    def retrieve(self, query: str, k: int,
                 lane: str = "operational") -> tuple[list[str], bool]:
        from .recall import recall
        r = recall(self._vault, query, k=k, embedder=self._embedder, lane=lane)
        if r.degraded:
            # Refuse to benchmark the PPR fallback under the hybrid name —
            # that would certify baseline numbers as cortex numbers.
            raise RuntimeError(f"recall degraded mid-bench ({r.note}); "
                               "hybrid numbers would be fake")
        return [h.note_name for h in r.hits], r.abstained


RETRIEVERS = {"ppr": PPRRetriever, "keyword": KeywordRetriever,
              "hybrid": HybridRetriever}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    probe: Probe
    retrieved: list[str]
    abstained: bool
    hit: bool
    recall: float
    rr: float
    passed: bool  # category-appropriate pass (hit for recall cats; abstain for abstention)


@dataclass
class BenchReport:
    retriever: str
    k: int
    vault_note_count: int
    results: list[ProbeResult] = field(default_factory=list)

    def by_category(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for cat in CATEGORIES:
            rs = [r for r in self.results if r.probe.category == cat]
            if not rs:
                continue
            n = len(rs)
            if cat == "abstention":
                out[cat] = {"n": n, "pass_rate": sum(r.passed for r in rs) / n}
            else:
                out[cat] = {
                    "n": n,
                    "hit@k": sum(r.hit for r in rs) / n,
                    "recall@k": sum(r.recall for r in rs) / n,
                    "mrr": sum(r.rr for r in rs) / n,
                }
        return out

    def overall(self) -> dict:
        recall_rs = [r for r in self.results if r.probe.category != "abstention"]
        out = {"probes": len(self.results)}
        if recall_rs:
            out["hit@k"] = sum(r.hit for r in recall_rs) / len(recall_rs)
            out["recall@k"] = sum(r.recall for r in recall_rs) / len(recall_rs)
            out["mrr"] = sum(r.rr for r in recall_rs) / len(recall_rs)
            # false-abstain: abstaining on an ANSWERABLE probe. Without this,
            # cranking the abstain floor games the abstention category with
            # no visible cost — the trade must be measured on both sides.
            out["false_abstain"] = sum(r.abstained for r in recall_rs) / len(recall_rs)
        return out

    def to_markdown(self) -> str:
        lines = [f"### Retriever `{self.retriever}` @ k={self.k} "
                 f"(vault: {self.vault_note_count} notes)", ""]
        lines.append("| category | n | hit@k | recall@k | mrr |")
        lines.append("|---|---|---|---|---|")
        for cat, m in self.by_category().items():
            if cat == "abstention":
                lines.append(f"| {cat} | {m['n']} | abstain-pass {m['pass_rate']:.2f} | — | — |")
            else:
                lines.append(f"| {cat} | {m['n']} | {m['hit@k']:.2f} | "
                             f"{m['recall@k']:.2f} | {m['mrr']:.2f} |")
        o = self.overall()
        if "hit@k" in o:
            lines.append(f"| **overall (recall cats)** | {o['probes']} | "
                         f"**{o['hit@k']:.2f}** | **{o['recall@k']:.2f}** | **{o['mrr']:.2f}** |")
            lines.append(f"\nfalse-abstain on answerable probes: {o['false_abstain']:.2f}")
        return "\n".join(lines)

    def failures(self) -> list[str]:
        out = []
        for r in self.results:
            if not r.passed:
                out.append(f"[{r.probe.category}] {r.probe.id}: {r.probe.query!r} "
                           f"-> got {r.retrieved[:5]} (gold {r.probe.gold}, "
                           f"abstained={r.abstained})")
        return out


def score_probe(probe: Probe, retrieved: list[str], abstained: bool) -> ProbeResult:
    gold = set(probe.gold)
    hit = bool(gold & set(retrieved))
    recall = (len(gold & set(retrieved)) / len(gold)) if gold else 0.0
    rr = 0.0
    for rank, name in enumerate(retrieved, 1):
        if name in gold:
            rr = 1.0 / rank
            break
    passed = abstained if probe.category == "abstention" else hit
    return ProbeResult(probe=probe, retrieved=retrieved, abstained=abstained,
                       hit=hit, recall=recall, rr=rr, passed=passed)


def run_bench(vault: Vault, probes: list[Probe], retriever_name: str,
              k: int = 8, retriever_kwargs: dict | None = None) -> BenchReport:
    missing = validate_gold(probes, vault)
    if missing:
        raise ValueError("gold validation failed:\n" + "\n".join(missing))
    retriever = RETRIEVERS[retriever_name](vault, **(retriever_kwargs or {}))
    note_count = sum(1 for _ in vault.iter_notes())
    report = BenchReport(retriever=retriever_name, k=k, vault_note_count=note_count)
    for probe in probes:
        retrieved, abstained = retriever.retrieve(probe.query, k, lane=probe.lane)
        report.results.append(score_probe(probe, retrieved, abstained))
    return report


__all__ = ["Probe", "ProbeResult", "BenchReport", "load_probes", "validate_gold",
           "run_bench", "RETRIEVERS", "CATEGORIES"]
