"""Audit R3 — RecallResult.seeds must be lane-pure on BOTH paths.

Regression: _degraded() lane-filtered result.ranked but returned PPRBoot's raw
seeds unfiltered, leaking cross-lane entity names verbatim through
RecallResult.seeds. The main (cortex) path filters seeds via _seedable before
pagerank; these tests pin BOTH, plus quarantine purity. The deeper PPRBoot
score-contamination issue (its internal graph is lane-blind) is on the
enhancement queue, explicitly NOT fixed here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro.embedder import FakeEmbedder
from weave.pro.recall import recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "lane-vault"

OPS_NAMES = {"entity-Client-Omega", "2025-02-12-omega-fm-build", "career-ladder",
             "signals-2025-02-20-vendor-lesson"}
THESIS_NAMES = {"entity-Thesis-Pilot", "2025-02-10-thesis-methods-review",
                "Draft Manuscript"}
QUARANTINED_NAMES = {"entity-DanaVo", "Dana", "entity-AtlasERP", "entity-Mira",
                     "consolidation-2025-04-05-1330",
                     "consolidation-2025-05-01-0800", "signals-2025-04-02",
                     "consolidation-2025-04-05-0910",
                     "consolidation-2025-04-05-1120"}

# Names both a thesis and an ops entity, so both would seed without filtering.
CROSS_LANE_QUERY = "thesis pilot and client omega connection"


class DeadEmbedder:
    name = "dead"

    def embed(self, texts):
        raise RuntimeError("connection refused")


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


def _assert_seed_purity(r, lane):
    banned = (THESIS_NAMES if lane == "operational" else OPS_NAMES) | QUARANTINED_NAMES
    leaked = set(r.seeds) & banned
    assert not leaked, f"seeds leaked cross-lane/quarantined names (lane={lane}): {leaked}"


def test_degraded_path_seeds_lane_pure(built_vault):
    """Degraded-path regression: embedder down -> degraded PPR boot -> seeds must
    still be lane-filtered (and quarantine-filtered), both directions."""
    for lane in ("thesis", "operational"):
        r = recall(built_vault, CROSS_LANE_QUERY, k=50,
                   embedder=DeadEmbedder(), lane=lane)
        assert r.degraded
        _assert_seed_purity(r, lane)
        # positive control: the SAME-lane entity still seeds (filter is not
        # just emptying the dict)
        expected = "entity-Thesis-Pilot" if lane == "thesis" else "entity-Client-Omega"
        assert expected in r.seeds


def test_degraded_path_seeds_quarantine_pure(built_vault):
    r = recall(built_vault, "what is Dana's thesis pseudonym", k=50,
               embedder=DeadEmbedder(), lane="operational")
    assert r.degraded
    assert not set(r.seeds) & QUARANTINED_NAMES


def test_main_path_seeds_lane_pure(built_vault):
    """Main (cortex) path: seeds filtered BEFORE pagerank, both directions."""
    for lane in ("thesis", "operational"):
        r = recall(built_vault, CROSS_LANE_QUERY, k=50,
                   embedder=FakeEmbedder(), lane=lane)
        assert not r.degraded
        _assert_seed_purity(r, lane)
        expected = "entity-Thesis-Pilot" if lane == "thesis" else "entity-Client-Omega"
        assert expected in r.seeds
