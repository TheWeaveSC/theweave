"""hydrate() eval harness — Tier-1 structural + Tier-2 mock_llm canaries.

MECHANISM only. The eval asserts properties of a RoleBundle; the canary FIXTURES
(entities/souls/signals) are supplied by the caller (live: the vault; tests:
tests/). Tier-2 uses the existing mock_llm so the harness runs offline with no
API key and no network.

Usage:
    from weave.pro.hydrate import hydrate
    from weave.pro.hydrate_eval import run_tier1, run_tier2, EvalResult
    bundle = hydrate(vault, "quill", domain="research", soul_root=...)
    report = run_tier1(bundle)
    assert report.ok, report.failures
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .hydrate import RoleBundle, _NEUTRALIZED
from .mock_llm import reflect_signals

# Un-neutralized role-delimiter detector (the thing the sanitizer must remove).
_DELIM_RE = re.compile(r"^(system|assistant|user|developer|tool)\s*:", re.IGNORECASE)


@dataclass
class EvalResult:
    tier: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{n}: {d}" for n, ok, d in self.checks if not ok]

    def to_markdown(self) -> str:
        lines = [f"## {self.tier}"]
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"- [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier 1 — structural (no model)
# ---------------------------------------------------------------------------


def run_tier1(bundle: RoleBundle, *, budget: int = 6000) -> EvalResult:
    """Structural invariants on a successfully hydrated bundle."""
    r = EvalResult(tier="Tier-1 structural")
    preamble = bundle.to_preamble(max_chars=budget)

    # 1. red_lines present
    r.add("red_lines present", bool(bundle.red_lines),
          "no red_lines extracted from soul")

    # 2. provenance resolvable (every item has a [src...] stamp)
    prov_ok = bool(bundle.provenance) and all(
        isinstance(v, str) and v.startswith("[") and v.endswith("]")
        for v in bundle.provenance.values()
    )
    r.add("provenance resolvable", prov_ok, "missing/malformed provenance stamps")

    # 3. zero un-neutralized role-delimiter tokens anywhere in the preamble
    leaked = []
    for line in preamble.splitlines():
        stripped = line.lstrip("- ").strip()
        if _DELIM_RE.match(stripped):
            leaked.append(line)
    r.add("zero un-neutralized delimiters", not leaked,
          f"leaked: {leaked[:3]}")

    # 4. chars <= budget
    r.add("chars <= budget", len(preamble) <= budget,
          f"{len(preamble)} > {budget}")

    # 5. charter allowlist holds (no known_issues leakage)
    r.add("charter allowlisted", "known_issues" not in bundle.charter,
          "known_issues leaked into charter")

    # 6. nonce fence present around T2
    suffix = bundle.memory_suffix()
    r.add("nonce fence present",
          "<<<WEAVE-MEMORY" in suffix and "<<<END-WEAVE-MEMORY" in suffix,
          "T2 nonce fence missing")

    return r


def assert_honest_empty(callable_raising) -> EvalResult:
    """Tier-1: assert that a missing soul/entity raises HydrationError."""
    from .hydrate import HydrationError
    r = EvalResult(tier="Tier-1 honest-empty")
    try:
        callable_raising()
        r.add("honest-empty raises", False, "expected HydrationError, got a bundle")
    except HydrationError:
        r.add("honest-empty raises", True)
    return r


# ---------------------------------------------------------------------------
# Tier 2 — mock_llm canaries (offline, deterministic)
# ---------------------------------------------------------------------------


def run_tier2(bundle: RoleBundle) -> EvalResult:
    """Canary probes using the existing mock_llm. Offline + deterministic.

    These are MECHANISM canaries: they verify the bundle carries the material a
    domain reviewer needs (fact-vs-interpretation discipline; refuse-blog-as-
    peer-reviewed), and that the reflect-pass over the bundle's signals does not
    surface an un-neutralized injection. The institutional canary SETS (which
    exact prompts/answers) live in the vault; this harness proves the plumbing.
    """
    r = EvalResult(tier="Tier-2 mock_llm canaries")

    # Canary A: the bundle's red_lines + guardrails carry the discipline a
    # researcher reviewer must apply. (Probes the material, not a live model.)
    text = (" ".join(bundle.red_lines) + " " + " ".join(bundle.guardrails)).lower()
    r.add("canary: fact-vs-interpretation present",
          "interpretation" in text or "fact" in text,
          "no fact/interpretation discipline in red_lines+guardrails")
    r.add("canary: refuse-blog-as-peer-reviewed present",
          "blog" in text or "peer-review" in text or "peer review" in text,
          "no blog/peer-review guardrail")

    # Canary B: run the mock reflect-pass over the bundle's domain signals; the
    # synthesis must not contain a live role-delimiter (injection survived as
    # neutralized text, never as an executable role line).
    synth = reflect_signals(bundle.signals)
    leaked = [ln for ln in synth.splitlines()
              if _DELIM_RE.match(ln.lstrip("- ").strip())]
    r.add("canary: reflect-pass no live delimiter", not leaked,
          f"reflect synthesis leaked a role line: {leaked[:2]}")

    return r


def run_all(bundle: RoleBundle, *, budget: int = 6000) -> list[EvalResult]:
    return [run_tier1(bundle, budget=budget), run_tier2(bundle)]


__all__ = ["EvalResult", "run_tier1", "run_tier2", "run_all", "assert_honest_empty"]
