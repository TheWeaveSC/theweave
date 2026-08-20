"""Repo-tree scrub-term sweep — zero private terms in anything shipped.

Maintainers keep their real private terms (project names, employer names,
pseudonyms, people) one-per-line in tests/scrub_terms.local.txt — gitignored,
so the terms themselves never land in the repo. When that file is absent
(every fresh clone / CI), the whole check SKIPS gracefully; the in-repo
canary test still proves the mechanism works.

Word-boundary matched so legitimate words do not false-positive on
substrings (e.g. "synthesis" must not trip a banned term "thesis").
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TERMS = Path(__file__).parent / "scrub_terms.local.txt"

# Text files shipped in the repo; binaries and generated dirs are skipped.
_TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".sh",
                  ".ps1", ".txt", ".cfg", ".ini"}
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", ".pytest_cache",
              "node_modules", ".ruff_cache", "dist", "build"}
_SKIP_FILES = {LOCAL_TERMS.name, Path(__file__).name}


def _iter_repo_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name in _SKIP_FILES:
            continue
        if path.suffix.lower() in _TEXT_SUFFIXES or path.name == "weave-cli":
            yield path


def _scan(terms: list[str]) -> list[str]:
    patterns = [re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
                for t in terms]
    hits: list[str] = []
    for path in _iter_repo_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in patterns:
            if pat.search(text):
                hits.append(f"{path.relative_to(REPO_ROOT)}: {pat.pattern}")
    return hits


def test_repo_tree_contains_no_private_terms() -> None:
    if not LOCAL_TERMS.exists():
        pytest.skip("tests/scrub_terms.local.txt absent — maintainer-only check")
    terms = [line.strip() for line in
             LOCAL_TERMS.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if not terms:
        pytest.skip("scrub_terms.local.txt present but empty")
    hits = _scan(terms)
    assert hits == [], f"private terms leaked into the repo tree: {hits}"


def test_scrub_mechanism_detects_planted_canary(tmp_path, monkeypatch) -> None:
    """Prove the scanner actually finds a term (the check above must never
    pass vacuously). The canary is assembled at runtime so this test file
    itself stays out of any term list."""
    canary = "weave-scrub-" + "canary-term"
    planted = REPO_ROOT / "tests" / "_scrub_canary_tmp.md"
    planted.write_text(f"has {canary} inside\n", encoding="utf-8")
    try:
        hits = _scan([canary])
        assert any("_scrub_canary_tmp.md" in h for h in hits)
    finally:
        planted.unlink()
    assert _scan([canary]) == []
