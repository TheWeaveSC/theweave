"""Hybrid recall — dense hits seed Personalized PageRank (W2, HippoRAG-2
pattern). The cortex read path.

Flow:  query ──embed──> dense top-m chunks ──max-per-note──> seed weights
       (∪ entity-name seeds) ──PPR over wikilink graph──> fused ranking
       score = α·dense + β·ppr (+ tiny spectral-proximity term)

Properties the boot path lacks, by design:
- paraphrase queries seed through MEANING, not just entity-name mention;
- superseded notes are INCLUDED in results (marked) — history is reachable;
- a confidence floor: when nothing in the vault is semantically close, the
  result says so (abstained=True) instead of returning confident junk.

I2: every recall verifies the manifest and reports staleness.
I6: with the cortex absent (or the embedder down) recall DEGRADES LOUDLY to
the plain PPR boot retriever — today's behavior, flagged as degraded.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np

from ..vault import Vault
from .cortex import (LANE_CONFIG_STALE_REASON, LaneConfigStale, cortex_dir,
                     lane_config_stale, read_manifest, verify_fresh)
from .dense import (LANES, dense_search, lane_of, load_lane_map,
                    unretrievable_files)
from .graphrep import load_graph, graph_to_networkx
from .ppr import PPRBoot, match_entity_names

# LaneConfigStale moved to cortex.py (audit H2: it is also raised at the
# dense data seam, and dense.py cannot import from this module). Re-exported
# here unchanged for existing callers.

# Fusion + abstention knobs — tuned on the W0 FIXTURE only, then validated
# untouched on the real snapshot (docs/CORTEX-RESULTS.md). Dense-dominant:
# the sweep showed PPR-heavy fusion lets hub entities crowd out the note that
# actually holds the answer; PPR contributes associative context, not rank 1.
ALPHA_DENSE = 1.0
BETA_PPR = 0.15
GAMMA_SPECTRAL = 0.05
DENSE_M = 24
# Empirical: answerable fixture queries bottom out at ~0.60 max-sim, junk
# tops out at ~0.68 — the distributions OVERLAP, so 0.64 is a best-cut, not a
# wall. False-abstains still return (flagged) hits; see CORTEX-RESULTS.md.
ABSTAIN_FLOOR = 0.64


@dataclass
class RecallHit:
    note_name: str
    rel_path: str
    score: float
    dense_sim: float
    ppr_score: float
    superseded: bool
    best_section: str = ""


@dataclass
class RecallResult:
    query: str
    hits: list[RecallHit] = field(default_factory=list)
    abstained: bool = False
    degraded: bool = False          # cortex absent / embedder down -> PPR-only
    stale: dict = field(default_factory=dict)   # I2: manifest mismatches
    seeds: dict = field(default_factory=dict)   # note -> personalization weight
    max_dense: float = 0.0
    note: str = ""                  # human-readable degradation/abstain reason

    def to_text(self, *, include_paths: bool = True) -> str:
        lines: list[str] = []
        header = "# Weave recall"
        if self.degraded:
            header += " — DEGRADED (cortex absent; PPR-only, reduced recall)"
        elif self.stale:
            header += f" — cortex STALE ({len(self.stale)} sources; `weave cortex rebuild`)"
        lines.append(header)
        lines.append(f"query: {self.query}")
        if self.note:
            lines.append(f"note: {self.note}")
        if self.abstained:
            lines.append("ABSTAINED: nothing in the vault is semantically close "
                         f"(max similarity {self.max_dense:.2f} < floor). "
                         "Results below are low-confidence.")
            lines.append("note: only the requested lane (+ neutral) was searched — "
                         "other lanes exist and were not searched (lane firewall; pick "
                         "explicitly with --lane / lane=, never auto-detected).")
        for i, h in enumerate(self.hits, 1):
            flags = " [superseded]" if h.superseded else ""
            line = f"{i}. {h.note_name}{flags} — score {h.score:.3f}"
            if include_paths:
                line += f" ({h.rel_path})"
            if h.best_section and h.best_section not in ("_head", "_frontmatter"):
                line += f" §{h.best_section}"
            lines.append(line)
        if not self.hits:
            lines.append("(no results)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Long-lived-process caches. The MCP server calls recall per agent turn;
# re-parsing graph.json and re-hashing the whole vault per query is wasted
# work whose inputs rarely change.
# ---------------------------------------------------------------------------

_graph_cache: dict[str, tuple[tuple[int, int], dict, "nx.DiGraph"]] = {}
_fresh_cache: dict[str, tuple[float, bool, dict]] = {}
_FRESH_TTL_S = 20.0
_telemetry_warned = False


def _cached_graph(cdir: Path) -> tuple[dict | None, "nx.DiGraph | None"]:
    p = cdir / "graph.json"
    try:
        st = p.stat()
    except OSError:
        return None, None
    key = str(p)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _graph_cache.get(key)
    if hit and hit[0] == sig:
        return hit[1], hit[2]
    payload = load_graph(cdir)
    if payload is None:
        return None, None
    g = graph_to_networkx(payload)
    _graph_cache[key] = (sig, payload, g)
    return payload, g


def _throttled_verify(vault: Vault, cdir: Path) -> tuple[bool, dict]:
    """verify_fresh re-reads + re-hashes EVERY vault file; per-query that
    dominates recall latency on an iCloud vault. Cache the verdict briefly —
    a <=20s-stale STALE banner is a fine trade for a fast read path."""
    key = str(cdir)
    now = time.monotonic()
    hit = _fresh_cache.get(key)
    if hit and now - hit[0] < _FRESH_TTL_S:
        return hit[1], hit[2]
    fresh, stale = verify_fresh(vault, cdir)
    _fresh_cache[key] = (now, fresh, stale)
    return fresh, stale


# ---------------------------------------------------------------------------
# The verb
# ---------------------------------------------------------------------------


def recall(vault: Vault, query: str, k: int = 8, *, embedder=None,
           m: int | None = None, floor: float | None = None,
           include_superseded: bool = True,
           lane: str = "operational") -> RecallResult:
    """Hybrid recall. READ-ONLY. Never raises on missing/broken cortex —
    degrades loudly to the PPR boot path instead (I6).

    `m`/`floor` default to the module knobs AT CALL TIME (a def-time default
    would freeze them and make tuning silently ineffective).
    `include_superseded=False` restores boot-style current-only results.

    `lane` (lane firewall): only notes in the requested lane OR neutral are
    retrievable. Enforced at three points — dense hits (in dense_search),
    PPR personalization seeds BEFORE pagerank runs (including entity-name-
    match seeds), and fusion candidates. Default operational.
    """
    if lane not in LANES:
        raise ValueError(f"unknown lane {lane!r} (expected one of {LANES})")
    if m is None:
        m = DENSE_M
    if floor is None:
        floor = ABSTAIN_FLOOR
    cdir = cortex_dir(vault)
    manifest = read_manifest(cdir)
    if manifest is None:
        return _degraded(vault, query, k, lane,
                         "cortex not built — run `weave cortex rebuild`")

    # audit R2c: lane-config drift is a HARD REFUSE, not a banner. The
    # check is a single small-file hash compare (no vault re-hash), done on
    # every recall — deliberately NOT behind the 20s freshness TTL, so a
    # lane_map edit can never be served even briefly. Markdown-content
    # staleness keeps its existing banner behaviour below.
    if lane_config_stale(manifest):
        raise LaneConfigStale(LANE_CONFIG_STALE_REASON)

    graph_payload, g = _cached_graph(cdir)
    if graph_payload is None:
        return _degraded(vault, query, k, lane, "cortex graph.json missing — rebuild")

    if embedder is None:
        from .embedder import default_embedder
        embedder = default_embedder()
    try:
        qvec = embedder.embed([query])[0]
    except Exception as e:  # embedder down: degrade loudly, never crash a read
        return _degraded(vault, query, k, lane, f"embedder unavailable ({e})")

    fresh, stale = _throttled_verify(vault, cdir)

    # 1. dense chunks -> per-note max similarity. FILTER POINT 1: dense_search
    # only returns chunks whose lane is the requested lane or neutral. Any
    # index failure (file deleted, db locked by a rebuild, corrupt) degrades —
    # never errors the verb, never fabricates an empty index.
    try:
        chunk_hits = dense_search(cdir, qvec, m=m, lane=lane)
    except LaneConfigStale:
        # H2: the data seam's own gate — never demote a correctness refusal
        # to a degraded read (the boot fallback would serve results).
        raise
    except Exception as e:
        return _degraded(vault, query, k, lane, f"dense index unavailable ({e})")
    note_sim: dict[str, float] = {}
    note_section: dict[str, str] = {}
    for note_name, _rel, section, sim in chunk_hits:
        if sim > note_sim.get(note_name, -1.0):
            note_sim[note_name] = sim
            note_section[note_name] = section
    max_dense = max(note_sim.values(), default=0.0)

    # 2. personalization: dense seeds (sharpened) ∪ entity-name seeds
    # (shared matcher with the boot retriever — one policy, no drift).
    # FILTER POINT 2: every seed is lane-checked BEFORE pagerank runs — an
    # entity-name mention of an out-of-lane entity must contribute zero PPR
    # mass — and hub/quarantined files (audit R1) are never seeded at all.
    nodes = graph_payload["nodes"]
    never_retrieve = unretrievable_files()  # hub exclusions ∪ quarantine

    def _seedable(name: str) -> bool:
        meta = nodes.get(name)
        if meta is None:
            return False
        # nodes from a pre-lane cortex have no lane key; builder-version
        # staleness already flags that cortex — treat missing as operational.
        node_lane = meta.get("lane", "operational")
        if node_lane not in (lane, "neutral"):
            return False
        return meta.get("rel_path") not in never_retrieve

    personalization: dict[str, float] = {}
    for name, sim in sorted(note_sim.items(), key=lambda kv: -kv[1])[:8]:
        if sim > 0 and _seedable(name):
            personalization[name] = sim * sim
    top_w = max(personalization.values(), default=1.0)
    for name in match_entity_names(query, nodes):
        if _seedable(name):
            personalization[name] = max(personalization.get(name, 0.0), top_w)
    seeds = dict(personalization)

    # 3. PPR over the artifact graph (cached DiGraph)
    if personalization:
        total = sum(personalization.values())
        pvec = {n: personalization.get(n, 0.0) / total for n in g.nodes}
        ppr_scores = nx.pagerank(g, alpha=0.85, personalization=pvec)
    else:
        ppr_scores = nx.pagerank(g, alpha=0.85)
    max_ppr = max(ppr_scores.values(), default=1.0)

    # 4. spectral proximity to the strongest dense seed (tiny tie-break term)
    spectral = graph_payload.get("spectral", {})
    anchor = max(note_sim, key=note_sim.get) if note_sim else None
    avec = np.array(spectral.get(anchor, [])) if anchor else None

    def spectral_sim(name: str) -> float:
        if avec is None or avec.size == 0:
            return 0.0
        v = np.array(spectral.get(name, []))
        if v.size == 0:
            return 0.0
        na, nv = np.linalg.norm(avec), np.linalg.norm(v)
        if na == 0 or nv == 0:
            return 0.0
        return float(avec @ v / (na * nv))

    # 5. fuse + rank. FILTER POINT 3: fusion candidates are lane-checked —
    # even PPR mass that reached an out-of-lane note through a neutral bridge
    # must never surface it in results — and quarantined bridge files
    # (audit R1) are never returned in ANY lane.
    candidates = set(note_sim) | {n for n, s in ppr_scores.items()
                                  if s > 0 and n in nodes}
    scored: list[RecallHit] = []
    for name in candidates:
        meta = nodes.get(name)
        if meta is None:
            continue
        if meta.get("rel_path") in never_retrieve:
            continue
        if meta.get("lane", "operational") not in (lane, "neutral"):
            continue
        if not include_superseded and meta.get("superseded"):
            continue
        dense_n = max(note_sim.get(name, 0.0), 0.0)
        ppr_n = ppr_scores.get(name, 0.0) / max_ppr
        score = ALPHA_DENSE * dense_n + BETA_PPR * ppr_n + GAMMA_SPECTRAL * spectral_sim(name)
        scored.append(RecallHit(
            note_name=name, rel_path=meta["rel_path"], score=score,
            dense_sim=dense_n, ppr_score=ppr_scores.get(name, 0.0),
            superseded=bool(meta.get("superseded")),
            best_section=note_section.get(name, "")))
    scored.sort(key=lambda h: (-h.score, h.note_name))
    hits = scored[:k]

    # W3 bookkeeping: log ABOUT the retrieval (I4) into the cortex, never the
    # vault (I5). Telemetry must never break a read — but dying silently
    # would starve the W3 evidence base, so the first failure warns once.
    # Read-only peer instances (WEAVE_READONLY) do not log: a governance
    # audit must not skew the owner's salience counters.
    if os.environ.get("WEAVE_READONLY", "").strip().lower() not in ("1", "true", "yes"):
        try:
            from .bookkeeping import log_retrieval
            log_retrieval(cdir, "recall", query, [h.note_name for h in hits],
                          session=os.environ.get("WEAVE_SESSION_ID", "local"))
        except Exception as e:
            global _telemetry_warned
            if not _telemetry_warned:
                _telemetry_warned = True
                print(f"weave-cortex: telemetry disabled this session ({e})",
                      file=sys.stderr)

    return RecallResult(query=query, hits=hits,
                        abstained=max_dense < floor,
                        degraded=False, stale=stale, seeds=seeds,
                        max_dense=max_dense)


def _degraded(vault: Vault, query: str, k: int, lane: str, why: str) -> RecallResult:
    """PPR-boot fallback. The boot path is lane-blind, so the firewall is
    re-applied here on the OUTPUT — an embedder outage must not become a
    cross-lane leak. lane_of() is re-derived from the vault (no cortex).

    audit R3: the SEEDS dict is filtered too — PPRBoot's raw seeds leak
    cross-lane entity names verbatim even when every hit is filtered. The
    deeper issue (PPRBoot's internal graph is lane-blind, so cross-lane
    seeds still contaminated the SCORES before this filter) is noted for
    the enhancement queue — not rebuilt here.
    audit R1: hub/quarantined files never appear in hits OR seeds."""
    lane_map = load_lane_map()
    never_retrieve = unretrievable_files(lane_map)
    boot = PPRBoot(vault)
    result = boot.run(query, top_n=k * 3)  # over-fetch: lane filter shrinks it

    def _visible(n) -> bool:
        return (n.rel_path not in never_retrieve
                and lane_of(n, lane_map) in (lane, "neutral"))

    hits = [RecallHit(note_name=n.name, rel_path=n.rel_path,
                      score=float(s), dense_sim=0.0, ppr_score=float(s),
                      superseded=bool(n.metadata.get("superseded_by")))
            for n, s in result.ranked if _visible(n)][:k]
    seed_notes = {s: boot._notes_by_name.get(s) for s in result.seeds}
    seeds = {s: 1.0 for s, n in seed_notes.items() if n is not None and _visible(n)}
    return RecallResult(query=query, hits=hits, abstained=not result.seeds,
                        degraded=True, note=why, seeds=seeds)


__all__ = ["recall", "RecallResult", "RecallHit", "LaneConfigStale",
           "ABSTAIN_FLOOR", "ALPHA_DENSE", "BETA_PPR", "GAMMA_SPECTRAL"]
