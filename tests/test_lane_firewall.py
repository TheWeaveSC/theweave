"""Lane firewall — leak tests (firewall spec, 8 tests).

Fixture: tests/fixtures/lane-vault — a fully synthetic demo vault (fictional
cast, invented dates), NEVER real vault content. Stand-in filenames/dirs are
chosen so the repo-root lane_map.yaml (the public demo seed — its example
rulings are matched to this fixture) classifies them through every rule
class (explicit ruling, filename glob, dir prefix, LearningLayer
vocabulary, default):

    thesis       entity-Thesis-Pilot, 2025-02-10-thesis-methods-review,
                 "HomeVault/Draft Manuscript.md" (explicit hot-file ruling)
    operational  entity-Client-Omega, 2025-02-12-omega-fm-build,
                 career-ladder (career/ prefix),
                 signals-2025-02-20-vendor-lesson (LL vocab rule)
    neutral      entity-seat-Blue (team/ prefix), Widget-Framework
                 (wiki/concepts/ prefix)
    hubs         BOOT.md, HomeVault/SESSION-NOTES-INDEX.md,
                 wiki/concepts/TheWeave-2.0.md — dense-excluded, never seeded

FakeEmbedder has no semantics — these tests pin the PARTITION (who can ever
appear), not ranking quality; real-model A/B evaluation is a separate job.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from weave.vault import Note, Vault
from weave.pro import cortex as cx
from weave.pro.dense import DENSE_DB, dense_excluded_files, lane_of
from weave.pro.embedder import FakeEmbedder
from weave.pro.graphrep import load_graph
from weave.pro.recall import recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "lane-vault"

THESIS_NAMES = {"entity-Thesis-Pilot", "2025-02-10-thesis-methods-review",
                "Draft Manuscript"}
OPS_NAMES = {"entity-Client-Omega", "2025-02-12-omega-fm-build", "career-ladder",
             "signals-2025-02-20-vendor-lesson"}
NEUTRAL_NAMES = {"entity-seat-Blue", "Widget-Framework", "BOOT",
                 "SESSION-NOTES-INDEX", "TheWeave-2.0"}
HUB_REL_PATHS = ("HomeVault/SESSION-NOTES-INDEX.md", "BOOT.md",
                 "wiki/concepts/TheWeave-2.0.md")


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    return Vault(vroot)


@pytest.fixture
def built_vault(vault) -> Vault:
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    return vault


def _names(result) -> set[str]:
    return {h.note_name for h in result.hits}


# (1) thesis-lane query never returns ops entities at any rank
def test_thesis_lane_never_returns_ops(built_vault):
    queries = [
        "thesis pilot study design methods",
        "Client Omega widget plant monthly close",   # names the ops entity outright
        "omega fm build financial model",
    ]
    for q in queries:
        r = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane="thesis")
        assert not r.degraded
        leaked = _names(r) & OPS_NAMES
        assert not leaked, f"ops notes leaked into thesis lane for {q!r}: {leaked}"


# (2) ops-lane query never returns thesis notes
def test_ops_lane_never_returns_thesis(built_vault):
    queries = [
        "omega widget plant close cycle",
        "thesis pilot interview protocol",    # names the thesis entity outright
    ]
    for q in queries:
        r = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane="operational")
        assert not r.degraded
        leaked = _names(r) & THESIS_NAMES
        assert not leaked, f"thesis notes leaked into ops lane for {q!r}: {leaked}"


# (3) default lane == operational behaviour
def test_default_lane_is_operational(built_vault):
    q = "omega widget plant close cycle"
    default = recall(built_vault, q, k=100, embedder=FakeEmbedder())
    explicit = recall(built_vault, q, k=100, embedder=FakeEmbedder(),
                      lane="operational")
    assert [h.note_name for h in default.hits] == [h.note_name for h in explicit.hits]
    assert not _names(default) & THESIS_NAMES
    with pytest.raises(ValueError):
        recall(built_vault, q, k=5, embedder=FakeEmbedder(), lane="bogus")


# (4) neutral notes visible from both lanes
def test_neutral_visible_from_both_lanes(built_vault):
    q = "what does seat blue handle"     # entity-name-seeds entity-seat-Blue
    for lane in ("thesis", "operational"):
        r = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane=lane)
        assert "entity-seat-Blue" in _names(r), \
            f"neutral note invisible from {lane} lane"


# (5) lane_of() regression pins for the hot-file rulings (repo lane_map.yaml)
def test_lane_of_hot_file_rulings():
    def pin(rel: str, raw: str = "") -> str:
        return lane_of(Note(path=Path("/x") / rel, rel_path=rel,
                            name=Path(rel).stem, metadata={},
                            content=raw, raw_text=raw))

    # thesis explicit rulings
    for rel in [
        "HomeVault/Draft Manuscript.md",
        "HomeVault/sessions/2025-03-04-methods-workshop.md",
        "HomeVault/sessions/2025-04-11-draft-review.md",
        "LearningLayer/signals-2025-03-30-writing-cadence.md",
        "HomeVault/entities/entity-Track-East.md",
        "HomeVault/entities/entity-Track-West.md",
    ]:
        assert pin(rel) == "thesis", rel
    # operational explicit rulings
    for rel in [
        "HomeVault/career/annual-review-notes.md",
        "HomeVault/entities/entity-DanaVo.md",
        "HomeVault/entities/entity-Mira.md",
        "HomeVault/entities/entity-Project-Warehouse-Rollout.md",
        "wiki/people/Dana.md",
    ]:
        assert pin(rel) == "operational", rel
    # neutral explicit + prefixes
    for rel in ["HomeVault/SESSION-NOTES-INDEX.md", "BOOT.md",
                "wiki/concepts/TheWeave-2.0.md",
                "HomeVault/team/entity-seat-Green.md",
                "wiki/concepts/Anything-Else.md"]:
        assert pin(rel) == "neutral", rel
    # wiki mirror inherits its source note's lane 1:1 (basename match)
    assert pin("wiki/sessions/2025-03-04-methods-workshop.md") == "thesis"
    # LearningLayer both-lane rule: vocabulary majority, tie -> operational
    assert pin("LearningLayer/signals-2025-01-01-x.md",
               "codebook fieldwork defence advisor") == "thesis"
    assert pin("LearningLayer/signals-2025-01-01-y.md",
               "shipment warranty quotation downtime") == "operational"
    assert pin("LearningLayer/signals-2025-01-01-z.md",
               "no lane vocabulary at all") == "operational"


# (6) graph.json contains zero direct thesis<->ops edges; neutral bridges stay;
# quarantined files are not graph nodes at all (audit H3)
def test_graph_has_no_cross_lane_edges(built_vault):
    payload = load_graph(cx.cortex_dir(built_vault))
    lanes = {name: meta["lane"] for name, meta in payload["nodes"].items()}
    for a, b in payload["edges"]:
        la, lb = lanes[a], lanes[b]
        assert not (la != lb and "neutral" not in (la, lb)), \
            f"cross-lane edge survived: {a} ({la}) -> {b} ({lb})"
    # the fixture DOES contain a thesis->ops wikilink; prove it was cut
    assert ["entity-Thesis-Pilot", "entity-Client-Omega"] \
        not in payload["edges"]
    # neutral bridges asserted still present
    assert ["SESSION-NOTES-INDEX", "entity-Thesis-Pilot"] in payload["edges"]
    assert ["SESSION-NOTES-INDEX", "entity-Client-Omega"] in payload["edges"]
    # audit H3: quarantined files never ROUTED — absent from nodes AND
    # edges entirely (the fixture's mega-hub stand-in is deliberately
    # well-linked; its topology must vanish with it).
    quarantined_names = {"entity-DanaVo", "Dana", "entity-AtlasERP",
                         "entity-Mira", "consolidation-2025-04-05-1330",
                         "consolidation-2025-05-01-0800", "signals-2025-04-02",
                         "consolidation-2025-04-05-0910",
                         "consolidation-2025-04-05-1120"}
    node_leak = set(payload["nodes"]) & quarantined_names
    assert not node_leak, f"quarantined files present as graph nodes: {node_leak}"
    edge_leak = [e for e in payload["edges"]
                 if e[0] in quarantined_names or e[1] in quarantined_names]
    assert not edge_leak, f"quarantined files present in edges: {edge_leak}"
    assert payload.get("spectral", {}).keys() == payload["nodes"].keys() or \
        not (set(payload.get("spectral", {})) & quarantined_names)


# (7) hub files produce zero rows in the chunks table
def test_hub_files_never_embedded(built_vault):
    db_path = cx.cortex_dir(built_vault) / DENSE_DB
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ph = ",".join("?" * len(HUB_REL_PATHS))
        n = db.execute(f"SELECT COUNT(*) FROM chunks WHERE rel_path IN ({ph})",
                       HUB_REL_PATHS).fetchone()[0]
        assert n == 0, f"hub files produced {n} chunk rows"
        # sanity: the exclusion list is exactly the three hub files
        assert set(dense_excluded_files()) == set(HUB_REL_PATHS)
        # and non-hub notes DID embed (the index is not trivially empty)
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    finally:
        db.close()


# (8) PPR seeds lane-filtered before pagerank (entity-name-match bypass case)
def test_ppr_seeds_lane_filtered_before_pagerank(built_vault):
    # The query NAMES the ops entity — entity-name matching would seed it;
    # the lane filter must drop it BEFORE pagerank, so it contributes zero
    # personalization mass and never surfaces.
    q = "Client Omega widget plant roadmap"
    r_thesis = recall(built_vault, q, k=100, embedder=FakeEmbedder(), lane="thesis")
    assert "entity-Client-Omega" not in r_thesis.seeds, \
        "out-of-lane entity-name seed reached pagerank"
    assert "entity-Client-Omega" not in _names(r_thesis)
    # positive control: same query in its own lane IS seeded
    r_ops = recall(built_vault, q, k=100, embedder=FakeEmbedder(),
                   lane="operational")
    assert "entity-Client-Omega" in r_ops.seeds
    # hub files are never seeded in any lane, even when named
    r_hub = recall(built_vault, "session notes index of everything", k=100,
                   embedder=FakeEmbedder(), lane="operational")
    assert "SESSION-NOTES-INDEX" not in r_hub.seeds
