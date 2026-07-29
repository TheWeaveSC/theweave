"""Personalized PageRank over the wikilink graph — Pattern 2.

Replaces the static boot file. Workflow:

    query string
      └─> extract entity names matching the vault
            └─> seed Personalized PageRank
                  └─> top-N notes (resolved through bi-temporal chain)
                        └─> format as boot context

Inspired by HippoRAG / HippoRAG 2 — minus the graph DB; we use the wikilink
substrate that already exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import networkx as nx

from ..vault import Note, Vault
from .bitemporal import BiTemporalResolver

_STOPWORDS = {"the", "and", "for", "you", "are", "with", "from", "this", "that",
              "have", "has", "was", "were", "but", "not", "all", "any", "out",
              "office", "project", "coverage"}


@dataclass
class BootResult:
    """Output of a PPR boot retrieval."""

    query: str
    seeds: list[str]            # entity names that seeded the PPR
    ranked: list[tuple[Note, float]]  # top-N notes with scores
    superseded_hops: list[tuple[str, str]]  # (queried_name, resolved_name) where chain hopped


class PPRBoot:
    """Build a wikilink graph and run Personalized PageRank from query-derived seeds."""

    def __init__(self, vault: Vault):
        self.vault = vault
        self.resolver = BiTemporalResolver(vault)
        self._graph: nx.DiGraph | None = None
        self._notes_by_name: dict[str, Note] = {}

    # ---------- graph build ----------

    def build(self) -> nx.DiGraph:
        """Build (or rebuild) the wikilink graph. Nodes = note names; edges = wikilinks."""
        g = nx.DiGraph()
        notes = list(self.vault.iter_notes())
        self._notes_by_name = {n.name: n for n in notes}
        for n in notes:
            g.add_node(n.name, type=n.metadata.get("type", "note"), path=n.rel_path)
        for n in notes:
            for target in n.wikilinks():
                # only link to nodes that actually exist in the vault
                if target in self._notes_by_name:
                    g.add_edge(n.name, target)
        self._graph = g
        return g

    # ---------- entity extraction ----------

    def extract_seeds(self, query: str) -> list[str]:
        """Find entity names mentioned in the query.

        Strategy: tokenise the stripped entity name and treat each token (>=3
        chars, not a stopword) as a possible seed key. Match those keys as
        whole words against the query (case-insensitive). Sessions and signals
        are excluded as seeds — they're not "things you orient around", they're
        evidence connected to entities.
        """
        if self._graph is None:
            self.build()
        q = " " + query.lower() + " "
        seeds: list[str] = []
        seen: set[str] = set()
        for name in self._notes_by_name:
            base = name.lower()
            if base.startswith(("session-", "signals-")):
                continue
            stripped = re.sub(r"^(entity-)", "", base)
            # Build candidate tokens: full stripped form + individual tokens
            tokens: list[str] = [stripped]
            for tok in re.split(r"[-_\s/]+", stripped):
                tok = tok.strip()
                if len(tok) >= 3 and tok not in _STOPWORDS:
                    tokens.append(tok)
            for tok in tokens:
                if re.search(rf"\b{re.escape(tok)}\b", q):
                    if name not in seen:
                        seeds.append(name)
                        seen.add(name)
                    break
        return seeds

    # ---------- PPR ----------

    def run(self, query: str, top_n: int = 8, alpha: float = 0.85) -> BootResult:
        """Run PPR seeded by entities extracted from query. Return top-N notes."""
        if self._graph is None:
            self.build()

        seeds = self.extract_seeds(query)
        # Resolve seeds through the bi-temporal chain — never seed on a superseded version
        hops: list[tuple[str, str]] = []
        resolved_seeds: list[str] = []
        seen_resolved: set[str] = set()
        for s in seeds:
            res = self.resolver.resolve(s)
            target = res.current.name if res.current else s
            if res.current and res.current.name != s:
                hops.append((s, res.current.name))
            if target not in seen_resolved:
                resolved_seeds.append(target)
                seen_resolved.add(target)

        if not resolved_seeds:
            # cold boot: no entities mentioned. Fall back to global PageRank.
            scores = nx.pagerank(self._graph, alpha=alpha)
        else:
            personalization = {n: 0.0 for n in self._graph.nodes}
            weight = 1.0 / len(resolved_seeds)
            for s in resolved_seeds:
                if s in personalization:
                    personalization[s] = weight
            scores = nx.pagerank(self._graph, alpha=alpha, personalization=personalization)

        ranked_names = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        ranked_notes: list[tuple[Note, float]] = []
        for name, score in ranked_names:
            note = self._notes_by_name.get(name)
            if note is None:
                continue
            # filter out superseded entities from the result (keep history accessible via chain)
            if note.metadata.get("superseded_by"):
                continue
            ranked_notes.append((note, score))
            if len(ranked_notes) >= top_n:
                break

        return BootResult(query=query, seeds=resolved_seeds, ranked=ranked_notes, superseded_hops=hops)

    # ---------- formatting ----------

    def format_boot(self, result: BootResult, *, include_excerpts: bool = True) -> str:
        """Render a PPR result as a human-readable boot context."""
        lines: list[str] = []
        lines.append("# 🪶 Weave Boot — query-driven")
        lines.append("")
        lines.append(f"**Query:** {result.query}")
        if result.seeds:
            lines.append(f"**Seeded by:** {', '.join(f'`{s}`' for s in result.seeds)}")
        else:
            lines.append("**Seeded by:** (cold boot — no entities matched; global PageRank used)")
        if result.superseded_hops:
            lines.append("")
            lines.append("**Bi-temporal hops applied (auto-resolved to current):**")
            for old, new in result.superseded_hops:
                lines.append(f"  - `{old}` → `{new}`")
        lines.append("")
        lines.append("## Top-N relevant notes")
        lines.append("")
        for i, (note, score) in enumerate(result.ranked, 1):
            ntype = note.metadata.get("type", "note")
            lines.append(f"### {i}. `{note.name}` ({ntype}) — score {score:.4f}")
            lines.append(f"  - path: `{note.rel_path}`")
            if include_excerpts:
                excerpt = _excerpt(note.content, 220)
                lines.append(f"  - excerpt: {excerpt}")
            lines.append("")
        return "\n".join(lines)


def _excerpt(text: str, max_chars: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
