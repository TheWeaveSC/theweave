"""MCP server exposing Weave Core's 5 verbs as tools.

Run with:
    WEAVE_VAULT_PATH=/path/to/vault python -m weave.mcp_server

Designed for Claude Desktop / Cowork. Zero infra — no Ollama, no DB.
"""

from __future__ import annotations

import os
import posixpath
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .core import WeaveCore, VaultPathError
from .vault import Vault
from .pro.hydrate import hydrate as _hydrate, HydrationError


def _vault_from_env() -> Vault:
    path = os.environ.get("WEAVE_VAULT_PATH")
    if not path:
        print(
            "ERROR: set WEAVE_VAULT_PATH to your vault directory before launching.",
            file=sys.stderr,
        )
        sys.exit(2)
    return Vault(Path(path).expanduser())


def _readonly_from_env() -> bool:
    """Peer-vault governance: a read-only instance exposes only `view`.

    Set WEAVE_READONLY=1 (true/yes) so a machine can READ a peer's vault over
    iCloud without ever writing to it. Single-writer-per-vault avoids iCloud
    conflict copies; cross-vault facts propagate by handoff, never direct write.
    """
    return os.environ.get("WEAVE_READONLY", "").strip().lower() in ("1", "true", "yes")


def _write_gate_enabled() -> bool:
    """Advisory write gate (v1). Default ON; WEAVE_WRITE_GATE=0/off/false/no
    disables. Checked per call (not at build time) so a long-running server
    honours the switch without a restart."""
    return os.environ.get("WEAVE_WRITE_GATE", "").strip().lower() not in (
        "0", "off", "false", "no")


def _canon_rel(path: str) -> str:
    """Canonical vault-relative form of a tool-supplied path: forward
    slashes, no leading '/', no './' or 'a/..' segments. The TF-IDF index
    keys candidates by Vault.rel() output, so the gate's exclude-self set
    must match that form exactly — './entities/entity-X.md' would otherwise
    dodge the exclusion and 'conflict' with its own just-written self."""
    p = posixpath.normpath(path.replace("\\", "/").lstrip("/"))
    return "" if p == "." else p


def _gate_applies(path: str) -> bool:
    """Gate targets: entity notes (entity-*.md anywhere in the vault) and
    LearningLayer signal files (path check only — cheap)."""
    norm = _canon_rel(path)
    basename = norm.rsplit("/", 1)[-1]
    if basename.startswith("entity-") and basename.endswith(".md"):
        return True
    return "/LearningLayer/" in f"/{norm}" and basename.endswith(".md")


def _format_advice(proposal) -> str:
    """Render a Proposal as the advisory block appended to a write result."""
    lines = [
        "",
        "",
        "[write-gate advisory — write already applied]",
        f"verdict: {proposal.verdict}",
        f"target: {proposal.target_path or '(n/a)'}",
        f"rationale: {proposal.rationale}",
    ]
    if proposal.findings:
        lines.append("candidates:")
        for f in proposal.findings:
            keys = f" (keys: {', '.join(f.conflicting_keys)})" if f.conflicting_keys else ""
            lines.append(f"  {f.score:.3f} {f.rel_path} [{f.flag}]{keys}")
    return "\n".join(lines)


def build_server() -> FastMCP:
    vault = _vault_from_env()
    core = WeaveCore(vault)
    readonly = _readonly_from_env()
    mcp = FastMCP("weave-core (ro)" if readonly else "weave-core")

    @mcp.tool()
    def view(path: str = "", view_start: int | None = None, view_end: int | None = None) -> str:
        """View a file or directory in the vault. Optionally restrict to a line range (1-indexed, inclusive)."""
        view_range = None
        if view_start is not None and view_end is not None:
            view_range = (view_start, view_end)
        return core.view(path, view_range)

    @mcp.tool()
    def hydrate(
        entity: str,
        domain: str | None = None,
        max_signals: int = 12,
        max_chars: int = 6000,
    ) -> str:
        """Hydrate an entity into an injectable role + memory preamble.

        STRICTLY READ-ONLY — never writes to the vault. Returns a tiered,
        security-bound preamble (identity + red_lines + charter + guardrails,
        then nonce-fenced domain memory/signals). Missing soul/entity or a
        superseded entity returns an honest '[hydrate-error] ...' string
        rather than a fabricated persona. Registered before the read-only
        guard so a WEAVE_READONLY peer can hydrate without any write verb.
        """
        try:
            bundle = _hydrate(vault, entity, domain=domain, max_signals=max_signals)
        except HydrationError as e:
            return f"[hydrate-error] {e}"
        return bundle.to_preamble(max_chars=max_chars)

    @mcp.tool()
    def recall(query: str, k: int = 8, lane: str = "operational") -> str:
        """Hybrid semantic recall over the vault (cortex: dense + graph PPR).

        READ-ONLY. Finds notes by MEANING, not just entity-name mention;
        includes superseded notes (marked) so history is reachable; abstains
        honestly when nothing in the vault is semantically close. With the
        cortex absent or the embedder down it degrades loudly to the plain
        PPR boot retriever (today's behavior) instead of failing.

        `lane` (lane firewall): one of "operational" (default), "thesis",
        "neutral". Only notes in the requested lane (or neutral) are ever
        retrievable — choosing a lane is a deliberate anonymisation-boundary
        decision, never auto-detected from the query.
        """
        try:
            from .pro.recall import recall as _recall
        except ImportError as e:
            # A server restarted onto this branch without `pip install -e .`
            # must answer honestly, not throw a raw tool error on first use.
            return (f"[recall-error] dependencies missing ({e}); run "
                    "`pip install -e .` in the server's environment. "
                    "view/hydrate remain available.")
        return _recall(vault, query, k=k, lane=lane).to_text()

    if readonly:
        # Read-only peer instance: write verbs are never registered, so
        # writing to the wrong vault is impossible by construction. `view`,
        # `hydrate` and `recall` (all read-only) are registered above this
        # guard.
        return mcp

    # ---- advisory write gate (v1) -------------------------------------
    # The resolver's TF-IDF index is built lazily, ONCE per process, on the
    # first gated write (latency guard: index build is the only expensive
    # step). Deterministic-only mode always (allow_llm=False): the gate must
    # never block a write on a network call. ANY resolver failure fails OPEN
    # — the write result is returned exactly as if the gate were off; a
    # memory write must never be lost to a gate bug.
    gate_state: dict = {"resolver": None}

    def _gate_resolver():
        if gate_state["resolver"] is None:
            from .pro.conflict import ConflictResolver
            gate_state["resolver"] = ConflictResolver(vault)
        return gate_state["resolver"]

    def _gate_advice(path: str) -> str:
        """Advisory proposal for a JUST-APPLIED write. Returns '' when the
        gate is off, the path is out of scope, or anything at all fails."""
        try:
            canon = _canon_rel(path)
            if not _write_gate_enabled() or not _gate_applies(canon):
                return ""
            content = vault.read_text(canon)
            name = canon.rsplit("/", 1)[-1].removesuffix(".md")
            proposal = _gate_resolver().propose(
                new_note_name=name,
                new_note_content=content,
                exclude={canon},
                allow_llm=False,
            )
            return _format_advice(proposal)
        except Exception as e:  # fail-open: advisory only, never lose a write
            print(f"[weave write-gate] advisory failed for {path}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return ""

    @mcp.tool()
    def create(path: str, content: str) -> str:
        """Create or overwrite a file at the given vault-relative path.

        Entity/signal writes get an ADVISORY conflict proposal appended
        (verdict + rationale + sibling candidates); the write always proceeds.
        """
        return core.create(path, content) + _gate_advice(path)

    @mcp.tool()
    def str_replace(path: str, old_str: str, new_str: str) -> str:
        """Replace exactly one occurrence of old_str with new_str in the given file."""
        return core.str_replace(path, old_str, new_str) + _gate_advice(path)

    @mcp.tool()
    def insert(path: str, line: int, content: str) -> str:
        """Insert content BEFORE the given 1-indexed line (line=0 prepends)."""
        return core.insert(path, line, content) + _gate_advice(path)

    @mcp.tool()
    def delete(path: str) -> str:
        """Delete a file (or empty directory) at the given vault-relative path."""
        return core.delete(path)

    return mcp


def main() -> None:
    mcp = build_server()
    mcp.run()


if __name__ == "__main__":
    main()
