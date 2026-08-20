"""Committed bench fixture sanity — the W0 baseline must stay runnable in CI.

These tests pin MECHANICS (fixture loads, gold names exist, both retrievers
run, easy probes hit), never exact scores — scores belong in docs/BASELINE.md,
and locking them in tests would punish honest re-measurement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.vault import Vault
from weave.pro.bench import load_probes, run_bench, validate_gold, CATEGORIES

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def bench_vault() -> Vault:
    return Vault(FIXTURES / "bench-vault")


@pytest.fixture(scope="module")
def probes():
    return load_probes(FIXTURES / "bench-probes.yaml")


def test_fixture_loads_and_gold_exists(bench_vault, probes):
    assert sum(1 for _ in bench_vault.iter_notes()) >= 20
    assert validate_gold(probes, bench_vault) == []


def test_probe_set_covers_all_categories(probes):
    cats = {p.category for p in probes}
    assert cats == set(CATEGORIES)
    assert len(probes) >= 20


def test_both_retrievers_run_full_set(bench_vault, probes):
    for name in ("ppr", "keyword"):
        report = run_bench(bench_vault, probes, name, k=8)
        assert len(report.results) == len(probes)
        assert "| category |" in report.to_markdown()


def test_easy_single_hop_is_findable(bench_vault, probes):
    """If NO baseline retriever can hit the easiest single-hop probes, the
    fixture is broken, not the retrievers."""
    easy = [p for p in probes if p.id in ("sh-01", "sh-02")]
    ppr = run_bench(bench_vault, easy, "ppr", k=8)
    kw = run_bench(bench_vault, easy, "keyword", k=8)
    for a, b in zip(ppr.results, kw.results):
        assert a.hit or b.hit, f"{a.probe.id} unfindable by every baseline"
