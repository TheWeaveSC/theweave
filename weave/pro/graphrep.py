"""Graph artifact for the cortex — wikilink graph + cheap spectral node
embeddings (W2, "node2vec-class, cheap").

The graph covers EVERY note (including sessions and superseded versions —
history stays reachable through recall, unlike the boot path). Spectral
embeddings come from the normalized Laplacian of the undirected wikilink
graph via scipy — no gensim/node2vec dependency, deterministic given the
graph (eigenvector sign is canonicalized).
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np

from ..vault import Vault
from .cortex import CORTEX_BUILDER_VERSION
from .dense import lane_of, load_lane_map, quarantined_files

GRAPH_JSON = "graph.json"
SPECTRAL_DIMS = 16


def build_graph_artifact(vault: Vault, cdir: Path, *, log=print,
                         notes: list | None = None) -> dict:
    if notes is None:
        notes = vault.iter_notes_sorted()

    lane_map = load_lane_map()
    # audit H3: quarantined bridge files are dropped as NODES entirely —
    # their edges vanish with them, so their topology can no longer perturb
    # PPR mass or rank order. Quarantine contract: never embedded, never
    # seeded, never returned, never ROUTED.
    quarantined = quarantined_files(lane_map)
    q_dropped = sum(1 for n in notes if n.rel_path in quarantined)
    notes = [n for n in notes if n.rel_path not in quarantined]

    names = {n.name for n in notes}
    if len(names) < len(notes):
        seen: dict[str, str] = {}
        for n in notes:
            if n.name in seen:
                log(f"⚠ graph: duplicate note stem {n.name!r} "
                    f"({seen[n.name]} vs {n.rel_path}) — last writer wins; "
                    "rename one or recall may point at the wrong file")
            seen[n.name] = n.rel_path

    nodes: dict[str, dict] = {}
    edges: list[list[str]] = []
    for n in notes:
        nodes[n.name] = {
            "rel_path": n.rel_path,
            "type": str(n.metadata.get("type", "note")),
            "superseded": bool(n.metadata.get("superseded_by")),
            "lane": lane_of(n, lane_map),
        }
    edges_cut = 0
    for n in notes:
        src_lane = nodes[n.name]["lane"]
        for target in n.wikilinks():
            if target in names and target != n.name:
                # lane firewall: HARD CUT any thesis<->operational edge —
                # never added, so no PPR mass can flow across lanes directly.
                # Neutral notes bridge both lanes by design.
                dst_lane = nodes[target]["lane"]
                if (src_lane != dst_lane
                        and "neutral" not in (src_lane, dst_lane)):
                    edges_cut += 1
                    continue
                edges.append([n.name, target])
    edges.sort()

    spectral = _spectral_embeddings(nodes, edges)

    payload = {"nodes": nodes, "edges": edges, "spectral": spectral,
               "spectral_dims": SPECTRAL_DIMS}
    (cdir / GRAPH_JSON).write_text(
        json.dumps(payload, indent=None, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")
    log(f"graph: {len(nodes)} nodes, {len(edges)} edges "
        f"({edges_cut} cross-lane edges cut, {q_dropped} quarantined nodes "
        f"dropped), spectral d={SPECTRAL_DIMS}")
    return {"kind": "wikilink-graph", "nodes": len(nodes), "edges": len(edges),
            "edges_cut": edges_cut, "quarantined_dropped": q_dropped,
            "spectral_dims": SPECTRAL_DIMS, "builder": CORTEX_BUILDER_VERSION}


def _spectral_embeddings(nodes: dict[str, dict], edges: list[list[str]]
                         ) -> dict[str, list[float]]:
    """d-dim spectral embedding of the undirected graph. Deterministic:
    fixed start vector, canonical sign (largest-|component| positive),
    rounded to 6 dp. Empty/tiny graphs degrade to zero vectors."""
    order = sorted(nodes)
    idx = {name: i for i, name in enumerate(order)}
    n = len(order)
    d = min(SPECTRAL_DIMS, max(n - 2, 0))
    if n == 0:
        return {}
    if d == 0 or not edges:
        return {name: [0.0] * SPECTRAL_DIMS for name in order}

    g = nx.Graph()
    g.add_nodes_from(range(n))
    g.add_edges_from((idx[a], idx[b]) for a, b in edges)

    # Dense eigh throughout: at vault scale (10^2–10^3 notes) it is fast,
    # and unlike shift-invert eigsh it has no singular-sigma edge cases and
    # is deterministic (LAPACK syevd, same input -> same output).
    lap = nx.normalized_laplacian_matrix(g, nodelist=range(n)).todense()
    _, vecs = np.linalg.eigh(np.asarray(lap))
    vecs = vecs[:, 1:d + 1] if n > d else vecs[:, :d]  # drop the trivial 0-mode

    # canonical sign per eigenvector
    for j in range(vecs.shape[1]):
        col = vecs[:, j]
        k = int(np.argmax(np.abs(col)))
        if col[k] < 0:
            vecs[:, j] = -col

    out: dict[str, list[float]] = {}
    for name in order:
        row = vecs[idx[name], :]
        padded = list(np.round(row, 6)) + [0.0] * (SPECTRAL_DIMS - vecs.shape[1])
        out[name] = [float(x) for x in padded]
    return out


def load_graph(cdir: Path) -> dict | None:
    p = cdir / GRAPH_JSON
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def graph_to_networkx(payload: dict) -> "nx.DiGraph":
    g = nx.DiGraph()
    for name, meta in payload["nodes"].items():
        g.add_node(name, **meta)
    g.add_edges_from((a, b) for a, b in payload["edges"])
    return g


__all__ = ["build_graph_artifact", "load_graph", "graph_to_networkx",
           "GRAPH_JSON", "SPECTRAL_DIMS"]
