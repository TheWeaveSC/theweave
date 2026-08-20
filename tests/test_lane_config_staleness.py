"""Audit R2 — lane-config staleness must be LOUD.

lane_map.yaml is a derivation input: a cache built under an older lane map
holds wrong lane values with no markdown edit to betray it.
The manifest carries lane_config_hash; recall HARD-REFUSES on mismatch
(distinct from markdown staleness, which keeps its banner behaviour).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro import cortex as cx
from weave.pro import dense
from weave.pro.embedder import FakeEmbedder
from weave.pro.recall import LaneConfigStale, recall

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "lane-vault"


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    vroot = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vroot)
    monkeypatch.setenv("WEAVE_CORTEX_DIR", str(tmp_path / "cortex-base"))
    # Redirect the lane map to a private copy so the test can edit it without
    # touching the repo file. All lane rules stay identical.
    lm_copy = tmp_path / "lane_map.yaml"
    shutil.copyfile(dense.LANE_MAP_FILE, lm_copy)
    monkeypatch.setattr(dense, "LANE_MAP_FILE", lm_copy)
    return Vault(vroot)


def test_manifest_carries_lane_config_hash(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    manifest = cx.read_manifest(cx.cortex_dir(vault))
    assert manifest["lane_config_hash"] == dense.lane_map_hash()


def test_recall_refuses_on_lane_config_drift_then_rebuild_recovers(vault):
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    # sanity: fresh build serves
    r = recall(vault, "omega widget plant close cycle", k=5,
               embedder=FakeEmbedder(), lane="operational")
    assert not r.degraded

    # drift: ANY content change to the lane map (even a comment) invalidates
    with open(dense.LANE_MAP_FILE, "a", encoding="utf-8") as fh:
        fh.write("\n# drift: simulated post-build lane ruling edit\n")

    with pytest.raises(LaneConfigStale, match="lane config changed"):
        recall(vault, "omega widget plant close cycle", k=5,
               embedder=FakeEmbedder(), lane="operational")

    # verify_fresh reports the distinct reason too (status/doctor path)
    fresh, stale = cx.verify_fresh(vault, cx.cortex_dir(vault))
    assert not fresh and "<lane-config>" in stale

    # rebuild under the edited map -> serves again
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    r = recall(vault, "omega widget plant close cycle", k=5,
               embedder=FakeEmbedder(), lane="operational")
    assert not r.degraded


def test_dense_search_refuses_on_drift_directly(vault):
    """audit H2 — hash gate at the data seam. A DIRECT dense_search()
    call (bypassing recall) on a drifted cache must raise LaneConfigStale:
    any caller — bench, future skills, CLI — inherits the refusal."""
    from weave.pro.dense import dense_search

    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    cdir = cx.cortex_dir(vault)
    qvec = FakeEmbedder().embed(["omega widget plant"])[0]
    assert dense_search(cdir, qvec, m=5, lane="operational") is not None  # serves

    with open(dense.LANE_MAP_FILE, "a", encoding="utf-8") as fh:
        fh.write("\n# drift: simulated post-build edit\n")
    with pytest.raises(LaneConfigStale, match="lane config changed"):
        dense_search(cdir, qvec, m=5, lane="operational")
    # the unfiltered legacy path must refuse too — the chunks are the same
    with pytest.raises(LaneConfigStale):
        dense_search(cdir, qvec, m=5, lane=None)

    # missing manifest = unverifiable lane provenance -> fail closed
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    (cdir / "manifest.json").unlink()
    with pytest.raises(LaneConfigStale, match="manifest missing"):
        dense_search(cdir, qvec, m=5, lane="operational")


def test_pre_r2_manifest_without_hash_refuses(vault):
    """Fail closed: a manifest with no lane_config_hash (pre-R2 cache) must
    refuse, not silently serve possibly-wrong lane values."""
    cx.rebuild(vault, embedder=FakeEmbedder(), log=lambda *_: None)
    cdir = cx.cortex_dir(vault)
    manifest = cx.read_manifest(cdir)
    del manifest["lane_config_hash"]
    cx.write_manifest(cdir, manifest)
    with pytest.raises(LaneConfigStale):
        recall(vault, "omega widget plant close cycle", k=5,
               embedder=FakeEmbedder(), lane="operational")
