"""Deterministic conflict pre-filter (Item 2) — weave.pro.conflict.

Contract under test:
  - overlapping normalized frontmatter keys with differing values on a
    related candidate -> hard_conflict + the offending keys;
  - near-duplicate content without contradiction -> likely_duplicate;
  - low similarity -> unrelated, and volatile keys (date, valid_from, ...)
    never count as contradictions;
  - unrelated/NOOP outcomes NEVER touch the LLM module; hard_conflict goes
    to the LLM only when a real one is configured, else the deterministic
    finding lands in the Proposal rationale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weave.pro.conflict import (
    HARD_CONFLICT, LIKELY_DUPLICATE, UNRELATED,
    ConflictResolver, prefilter,
)
from weave.vault import Vault


ACME_BODY = (
    "ACME production database migration. Replication lag stayed under the "
    "agreed threshold after WAL tuning. Migration window confirmed with the "
    "platform team and rollback rehearsed."
)

ENTITY_ACME = f"""---
type: entity
status: current
owner: marcus
environment: staging
---

# ACME

{ACME_BODY}
"""

# Same subject/body, contradicting owner + environment.
ENTITY_ACME_CONFLICT = f"""---
type: entity
status: current
owner: sarah
environment: production
---

# ACME

{ACME_BODY}
"""

# Same subject/body, IDENTICAL comparable frontmatter (only volatile keys differ).
ENTITY_ACME_TWIN = f"""---
type: entity
status: current
owner: marcus
environment: staging
date: '2026-08-19'
---

# ACME

{ACME_BODY}
"""

UNRELATED_GARDEN = """---
type: entity
status: current
owner: heng
---

# Gardening

Tomatoes, compost rotation, and drip irrigation schedules for the allotment.
Mulch depth and watering cadence for the dry season.
"""


# ---------- prefilter unit tests (no vault needed) ----------

def test_prefilter_flags_frontmatter_contradiction():
    candidates = [("entities/entity-ACME.md", 0.9,
                   {"type": "entity", "status": "current",
                    "owner": "marcus", "environment": "staging"})]
    findings = prefilter(ENTITY_ACME_CONFLICT, candidates)
    assert len(findings) == 1
    f = findings[0]
    assert f.flag == HARD_CONFLICT
    assert f.conflicting_keys == ["environment", "owner"]


def test_prefilter_near_duplicate_without_contradiction():
    candidates = [("entities/entity-ACME.md", 0.9,
                   {"type": "entity", "status": "current",
                    "owner": "marcus", "environment": "staging"})]
    findings = prefilter(ENTITY_ACME_TWIN, candidates)
    assert findings[0].flag == LIKELY_DUPLICATE
    assert findings[0].conflicting_keys == []


def test_prefilter_low_similarity_is_unrelated_even_with_shared_keys():
    """Every note disagrees with every other note on SOME shared key; that is
    only a conflict when the notes are actually about the same thing."""
    candidates = [("entities/entity-Garden.md", 0.05,
                   {"type": "entity", "status": "current", "owner": "heng"})]
    findings = prefilter(ENTITY_ACME_CONFLICT, candidates)
    assert findings[0].flag == UNRELATED
    assert findings[0].conflicting_keys == []


def test_prefilter_volatile_keys_never_conflict():
    candidates = [("entities/entity-ACME.md", 0.9,
                   {"type": "entity", "status": "current", "owner": "marcus",
                    "environment": "staging", "date": "2026-01-01",
                    "valid_from": "2025-01-01", "version": "1.0"})]
    findings = prefilter(ENTITY_ACME_TWIN, candidates)
    assert findings[0].flag == LIKELY_DUPLICATE


def test_prefilter_normalizes_keys_and_values():
    candidates = [("entities/entity-ACME.md", 0.9,
                   {"Owner": "  MARCUS ", "environment": "production",
                    "type": "entity", "status": "current"})]
    # new note has `owner: marcus` — matches after normalization; environment contradicts
    findings = prefilter(ENTITY_ACME, candidates)
    assert findings[0].flag == HARD_CONFLICT
    assert findings[0].conflicting_keys == ["environment"]


def test_prefilter_survives_malformed_new_note_frontmatter():
    broken = "---\nowner: [unclosed\n---\n\n# X\n" + ACME_BODY
    candidates = [("entities/entity-ACME.md", 0.9,
                   {"owner": "marcus", "status": "current"})]
    findings = prefilter(broken, candidates)  # must not raise
    assert findings[0].flag in (HARD_CONFLICT, LIKELY_DUPLICATE)


# ---------- resolver-level LLM routing ----------

@pytest.fixture
def vault(tmp_path, monkeypatch):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "entity-ACME.md").write_text(ENTITY_ACME, encoding="utf-8")
    (tmp_path / "entities" / "entity-Garden.md").write_text(UNRELATED_GARDEN, encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Vault(tmp_path)


class _CountingLLM:
    def __init__(self):
        self.calls = 0

    def classify_write(self, **kwargs):
        self.calls += 1
        from weave.pro.mock_llm import ClassifyResult
        return ClassifyResult(verdict="UPDATE", target_path="entities/entity-ACME.md",
                              rationale="llm says update", is_mock=False)


def test_unrelated_skips_llm_entirely(vault, monkeypatch):
    import weave.pro.conflict as conflict
    stub = _CountingLLM()
    monkeypatch.setattr(conflict, "get_llm", lambda: stub)
    monkeypatch.setattr(conflict, "is_mock", lambda: False)  # even a "real" LLM is skipped
    r = ConflictResolver(vault)
    p = r.propose(new_note_name="entity-Sky",
                  new_note_content="---\ntype: entity\n---\n\n# Sky\nCloud shapes and telescopes.")
    assert stub.calls == 0
    assert p.llm_called is False
    assert p.verdict == "ADD"
    assert "[prefilter]" in p.rationale


def test_noop_on_near_identical_skips_llm(vault, monkeypatch):
    import weave.pro.conflict as conflict
    stub = _CountingLLM()
    monkeypatch.setattr(conflict, "get_llm", lambda: stub)
    monkeypatch.setattr(conflict, "is_mock", lambda: False)
    r = ConflictResolver(vault)
    p = r.propose(new_note_name="entity-ACME",
                  new_note_content="# ACME\n\n" + ACME_BODY)
    assert stub.calls == 0
    assert p.verdict == "NOOP"
    assert p.target_path == "entities/entity-ACME.md"


def test_hard_conflict_goes_to_llm_when_configured(vault, monkeypatch):
    import weave.pro.conflict as conflict
    stub = _CountingLLM()
    monkeypatch.setattr(conflict, "get_llm", lambda: stub)
    monkeypatch.setattr(conflict, "is_mock", lambda: False)
    r = ConflictResolver(vault)
    p = r.propose(new_note_name="entity-ACME-v2", new_note_content=ENTITY_ACME_CONFLICT)
    assert stub.calls == 1
    assert p.llm_called is True
    assert p.verdict == "UPDATE"
    # deterministic finding still rides along in the rationale
    assert "Hard frontmatter conflict" in p.rationale


def test_hard_conflict_without_llm_surfaces_deterministic_finding(vault, monkeypatch):
    import weave.pro.conflict as conflict
    stub = _CountingLLM()
    monkeypatch.setattr(conflict, "get_llm", lambda: stub)  # would count if called
    r = ConflictResolver(vault)  # no ANTHROPIC_API_KEY -> is_mock() is True
    p = r.propose(new_note_name="entity-ACME-v2", new_note_content=ENTITY_ACME_CONFLICT)
    assert stub.calls == 0
    assert p.verdict == "UPDATE"
    assert p.target_path == "entities/entity-ACME.md"
    assert "Hard frontmatter conflict" in p.rationale
    assert "owner" in p.rationale and "environment" in p.rationale


def test_allow_llm_false_never_calls_even_configured_llm(vault, monkeypatch):
    import weave.pro.conflict as conflict
    stub = _CountingLLM()
    monkeypatch.setattr(conflict, "get_llm", lambda: stub)
    monkeypatch.setattr(conflict, "is_mock", lambda: False)
    r = ConflictResolver(vault)
    p = r.propose(new_note_name="entity-ACME-v2",
                  new_note_content=ENTITY_ACME_CONFLICT, allow_llm=False)
    assert stub.calls == 0
    assert p.verdict == "UPDATE"
    assert "Hard frontmatter conflict" in p.rationale


def test_exclude_drops_the_target_itself(vault, monkeypatch):
    """A write gate excludes the target path so a note never conflicts with
    its own prior version."""
    r = ConflictResolver(vault)
    p = r.propose(new_note_name="entity-ACME",
                  new_note_content=ENTITY_ACME_CONFLICT,
                  exclude={"entities/entity-ACME.md"},
                  allow_llm=False)
    assert all(path != "entities/entity-ACME.md" for path, _ in p.candidates)
