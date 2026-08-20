"""Bench harness mechanics — Cortex W0. Fixtures are synthetic and inline."""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro.bench import (
    Probe,
    load_probes,
    run_bench,
    score_probe,
    validate_gold,
)


@pytest.fixture
def bench_vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / "entities").mkdir(parents=True)
    (root / "sessions").mkdir()
    (root / "entities" / "entity-Rocket.md").write_text(
        "---\ntype: project\nstatus: current\n---\n"
        "# Rocket\nThe rocket project uses hydrazine fuel.\n"
        "## Links\n- [[session-2026-01-05-rocket-fuel]]\n",
        encoding="utf-8")
    (root / "sessions" / "session-2026-01-05-rocket-fuel.md").write_text(
        "---\ntype: session\n---\n# Fuel decision\n"
        "Chose hydrazine over kerosene. Tank pressure set to 220 bar.\n"
        "[[entity-Rocket]]\n",
        encoding="utf-8")
    (root / "entities" / "entity-Garden.md").write_text(
        "---\ntype: project\nstatus: current\n---\n# Garden\nTomatoes and basil.\n",
        encoding="utf-8")
    return Vault(root)


def test_load_probes_and_validation(tmp_path: Path, bench_vault: Vault):
    pf = tmp_path / "probes.yaml"
    pf.write_text(
        "- id: sh-01\n  category: single-hop\n"
        "  query: What tank pressure did the rocket fuel decision set?\n"
        "  gold: [session-2026-01-05-rocket-fuel]\n"
        "- id: ab-01\n  category: abstention\n"
        "  query: What is the capital of Mars?\n  gold: []\n",
        encoding="utf-8")
    probes = load_probes(pf)
    assert len(probes) == 2
    assert validate_gold(probes, bench_vault) == []


def test_gold_validation_catches_typo(bench_vault: Vault):
    probes = [Probe(id="x", category="single-hop", query="q",
                    gold=["session-does-not-exist"])]
    missing = validate_gold(probes, bench_vault)
    assert missing and "session-does-not-exist" in missing[0]
    with pytest.raises(ValueError):
        run_bench(bench_vault, probes, "keyword")


def test_probe_schema_rejects_bad_category_and_gold():
    with pytest.raises(ValueError):
        Probe(id="x", category="nope", query="q", gold=["a"])
    with pytest.raises(ValueError):
        Probe(id="x", category="abstention", query="q", gold=["a"])
    with pytest.raises(ValueError):
        Probe(id="x", category="single-hop", query="q", gold=[])


def test_scoring():
    p = Probe(id="x", category="single-hop", query="q", gold=["a", "b"])
    r = score_probe(p, ["z", "a", "y"], abstained=False)
    assert r.hit and r.passed
    assert r.recall == 0.5
    assert r.rr == 0.5
    ab = Probe(id="y", category="abstention", query="q", gold=[])
    assert score_probe(ab, [], abstained=True).passed
    assert not score_probe(ab, ["a"], abstained=False).passed


def test_keyword_retriever_finds_gold(bench_vault: Vault):
    probes = [Probe(id="sh-01", category="single-hop",
                    query="What tank pressure did the hydrazine fuel decision set?",
                    gold=["session-2026-01-05-rocket-fuel"])]
    report = run_bench(bench_vault, probes, "keyword", k=3)
    assert report.results[0].hit
    assert report.overall()["mrr"] > 0


def test_ppr_retriever_runs_and_abstains(bench_vault: Vault):
    probes = [
        Probe(id="sh-01", category="single-hop",
              query="What fuel does the rocket project use?",
              gold=["entity-Rocket"]),
        Probe(id="ab-01", category="abstention",
              query="What is the capital of Mars?", gold=[]),
    ]
    report = run_bench(bench_vault, probes, "ppr", k=3)
    by_id = {r.probe.id: r for r in report.results}
    assert by_id["sh-01"].hit          # 'rocket' seeds entity-Rocket
    assert by_id["ab-01"].abstained    # no entity matched -> cold boot
    assert by_id["ab-01"].passed


def test_bench_deterministic(bench_vault: Vault):
    probes = [Probe(id="sh-01", category="single-hop",
                    query="rocket fuel tank pressure",
                    gold=["session-2026-01-05-rocket-fuel"])]
    a = run_bench(bench_vault, probes, "keyword", k=3)
    b = run_bench(bench_vault, probes, "keyword", k=3)
    assert a.results[0].retrieved == b.results[0].retrieved
    assert a.to_markdown() == b.to_markdown()


def test_report_markdown_shape(bench_vault: Vault):
    probes = [
        Probe(id="sh-01", category="single-hop",
              query="rocket hydrazine fuel", gold=["entity-Rocket"]),
        Probe(id="ab-01", category="abstention",
              query="capital of Mars", gold=[]),
    ]
    md = run_bench(bench_vault, probes, "keyword", k=3).to_markdown()
    assert "| category |" in md and "single-hop" in md and "abstention" in md
