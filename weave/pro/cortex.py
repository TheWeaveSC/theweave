"""Weave Cortex — derived acceleration layer scaffold (W1).

STRICT CACHE SEMANTICS (I1): everything under the cortex dir is
derived from (markdown, model, builder version) and rebuildable; deleting it
loses speed, never memory. Markdown stays the single source of truth.

Layout (per vault, resolved OUTSIDE the vault tree — I3):

    ~/Library/Caches/theweave/<vault-id>/
        manifest.json      derivation manifest (I2) — deterministic, no clocks
        dense.sqlite3      chunk store + sqlite-vec index          (W2)
        graph.json         wikilink graph + spectral embeddings    (W2)
        bookkeeping.db     retrieval log / salience / co-occurrence (W3)
        proposals/         proposal reports (I5 — never vault writes)
        scratch/           sleep-time scratch, deleted after use   (W4)

The manifest is the byte-comparable rebuild artifact: same vault content +
same model + same builder version => byte-identical manifest.json. (SQLite
page layout is not byte-stable; the manifest's per-source content hashes are
what prove derivation.) bookkeeping.db is operational telemetry, NOT a
derived artifact — it is excluded from the manifest by design; losing it
loses stats, never memory (I4 allows logs-about-retrieval only).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..vault import Note, Vault, content_hash

# v0.5 item 18 changed what `sources` CONTAINS (quarantined files excluded), so
# an old manifest is not merely stale, it is differently-shaped. Bumping the
# builder version makes verify_fresh() report a clean "builder X != Y, rebuild"
# instead of 10 phantom `removed` entries that look like vault deletions.
CORTEX_BUILDER_VERSION = "cortex-w2.4-readpath"  # + item 15 raw-byte freshness, item 18 quarantine-excluded sources
EMBED_MODEL = "nomic-embed-text"
EMBED_DIMS = 768
MANIFEST_NAME = "manifest.json"

# Note dirs that feed the index (entities/signals/wiki per plan W2; sessions
# stay out of the dense index for now — they are evidence reachable through
# the graph, and embedding them would double index size for little seed value).
INDEXED_TYPES_HINT = "entities + LearningLayer + wiki (+ graph over ALL notes)"


# ---------------------------------------------------------------------------
# Path resolution (I3 — never inside the vault tree, never synced)
# ---------------------------------------------------------------------------


def vault_id(vault: Vault) -> str:
    """Stable per-vault id derived from the resolved vault root path."""
    return hashlib.sha256(str(vault.root).encode("utf-8")).hexdigest()[:16]


def cortex_dir(vault: Vault, *, create: bool = False) -> Path:
    """Resolve the cortex dir for a vault.

    Default: ~/Library/Caches/theweave/<vault-id>/ — macOS-native cache
    location, outside every iCloud-synced tree, excluded from Time Machine.
    WEAVE_CORTEX_DIR overrides the BASE dir (tests, non-mac platforms); the
    per-vault id subdir always applies so two vaults never share a cortex.
    """
    base = os.environ.get("WEAVE_CORTEX_DIR")
    root = (Path(base).expanduser() if base
            else Path("~/Library/Caches/theweave").expanduser())
    d = root / vault_id(vault)
    resolved = str(d.resolve())
    # I3 guards: never inside the vault tree, never inside an iCloud-synced
    # tree (a WEAVE_CORTEX_DIR pointing into Mobile Documents would sync
    # embeddings + telemetry across machines with zero errors).
    try:
        d.resolve().relative_to(vault.root)
        raise RuntimeError(
            f"cortex dir {d} resolves INSIDE the vault tree {vault.root}; "
            "refusing (I3: cortex is never synced)")
    except ValueError:
        pass  # good — outside the vault
    if "Mobile Documents" in resolved or "com~apple~CloudDocs" in resolved:
        raise RuntimeError(
            f"cortex dir {d} resolves inside iCloud; refusing "
            "(I3: cortex is rebuilt per machine, never synced)")
    if create:
        d.mkdir(parents=True, exist_ok=True)
        (d / "proposals").mkdir(exist_ok=True)
        (d / "scratch").mkdir(exist_ok=True)
    return d


def cortex_exists(vault: Vault) -> bool:
    return (cortex_dir(vault) / MANIFEST_NAME).is_file()


# ---------------------------------------------------------------------------
# Derivation manifest (I2)
# ---------------------------------------------------------------------------


def source_map(vault: Vault, notes: list[Note] | None = None) -> dict[str, str]:
    """rel_path -> content hash for every note in the vault (sorted keys).
    Pass `notes` to hash a single already-materialized snapshot — rebuild()
    must hash exactly what the builders indexed, not a re-walk (TOCTOU).

    Without `notes` this hashes RAW BYTES and never parses frontmatter
    (2026-08-13). Freshness never needed the parse, and routing it through one
    put every caller — including live `recall()`, which re-verifies on each
    query — behind a YAML syntax error in any single note. The file SELECTION
    is identical either way (both walk `Vault.note_paths()`), so the two forms
    stay comparable; only the parse is skipped.

    Quarantined files are EXCLUDED (v0.5 item 18). They feed zero artifacts —
    graphrep drops them as nodes before building and dense_eligible() refuses
    them — so an edit to one used to flip the whole cortex STALE while not a
    byte of dense.sqlite3 or graph.json could change. Excluding them cannot
    mask a quarantine-status change, because MEMBERSHIP lives in lane_map.yaml
    and is caught independently by lane_config_hash failing closed.

    Deliberately `quarantined_files()`, NOT `unretrievable_files()`: the hub
    exclusions in that wider set are dropped from the dense index but are still
    graph nodes, so their content really does feed an artifact and must keep
    invalidating the cache.
    """
    from .dense import quarantined_files  # lazy: dense imports this module
    skip = quarantined_files()
    if notes is None:
        return {rel: content_hash(raw) for rel, raw in vault.iter_raw_sorted()
                if rel not in skip}
    return {n.rel_path: content_hash(n.raw_text) for n in notes
            if n.rel_path not in skip}


def build_manifest(vault: Vault, artifacts: dict[str, dict],
                   notes: list[Note] | None = None) -> dict:
    """Deterministic manifest: same vault content + model + builder version
    + lane config => byte-identical JSON. NO wall-clock fields, by
    construction. lane_config_hash (audit R2): the lane map is a
    derivation input — a cache built under a different lane_map.yaml holds
    stale lane values with no markdown edit to betray it."""
    from .dense import lane_map_hash  # lazy: dense imports this module
    return {
        "manifest_version": 1,
        "builder_version": CORTEX_BUILDER_VERSION,
        "embed_model": EMBED_MODEL,
        "embed_dims": EMBED_DIMS,
        "vault_id": vault_id(vault),
        "lane_config_hash": lane_map_hash(),
        "sources": source_map(vault, notes),
        "artifacts": artifacts,
    }


def write_manifest(cdir: Path, manifest: dict) -> Path:
    p = cdir / MANIFEST_NAME
    p.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p


def read_manifest(cdir: Path) -> dict | None:
    p = cdir / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def stale_sources(vault: Vault, manifest: dict) -> dict[str, str]:
    """Sources whose content no longer matches the manifest (edit/add/remove).

    Returns rel_path -> reason ('changed' | 'added' | 'removed').
    """
    current = source_map(vault)
    recorded = manifest.get("sources", {})
    out: dict[str, str] = {}
    for rel, h in current.items():
        if rel not in recorded:
            out[rel] = "added"
        elif recorded[rel] != h:
            out[rel] = "changed"
    for rel in recorded:
        if rel not in current:
            out[rel] = "removed"
    return out


def verify_fresh(vault: Vault, cdir: Path | None = None,
                 manifest: dict | None = None) -> tuple[bool, dict[str, str]]:
    """Manifest check for every cortex READ (I2). (fresh?, stale map).
    Pass an already-parsed `manifest` to avoid a second read of the same file
    (status() would otherwise TOCTOU itself)."""
    cdir = cdir or cortex_dir(vault)
    if manifest is None:
        manifest = read_manifest(cdir)
    if manifest is None:
        return False, {"<manifest>": "missing"}
    if manifest.get("builder_version") != CORTEX_BUILDER_VERSION:
        return False, {"<manifest>": f"builder {manifest.get('builder_version')} "
                                     f"!= {CORTEX_BUILDER_VERSION}"}
    if lane_config_stale(manifest):
        return False, {"<lane-config>": LANE_CONFIG_STALE_REASON}
    stale = stale_sources(vault, manifest)
    return not stale, stale


LANE_CONFIG_STALE_REASON = ("lane config changed since build — rebuild "
                            "required (`weave cortex rebuild`)")


class LaneConfigStale(RuntimeError):
    """lane_map.yaml changed after this cortex was built (audit R2/H2).
    Serving cached lane values computed under an older lane config is a
    silent-leak vector, not a staleness banner — REFUSE and rebuild. Raised
    at the dense data seam (dense_search) so EVERY caller inherits the
    refusal, and redundantly in recall()."""


def lane_config_stale(manifest: dict) -> bool:
    """True when the cache was built under a different lane_map.yaml than the
    one on disk now (audit R2). A missing hash (pre-R2 manifest) counts as
    stale — fail closed. Distinct from markdown staleness: this is a
    correctness failure recall must REFUSE on, not banner over."""
    from .dense import lane_map_hash  # lazy: dense imports this module
    return manifest.get("lane_config_hash") != lane_map_hash()


# ---------------------------------------------------------------------------
# Build / status / clear (I1)
# ---------------------------------------------------------------------------


@dataclass
class CortexStatus:
    vault_root: str
    cortex_path: str
    exists: bool
    fresh: bool
    note_count: int
    stale: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, dict] = field(default_factory=dict)

    def to_text(self) -> str:
        lines = [f"vault:  {self.vault_root}",
                 f"cortex: {self.cortex_path}"]
        if not self.exists:
            lines.append("status: ABSENT — read path degrades to markdown-only "
                         "(reduced recall); run `weave cortex rebuild`")
            return "\n".join(lines)
        lines.append(f"status: {'FRESH' if self.fresh else 'STALE'} "
                     f"({self.note_count} notes indexed)")
        for name, meta in sorted(self.artifacts.items()):
            desc = ", ".join(f"{k}={v}" for k, v in sorted(meta.items())
                             if k not in ("sources",))
            lines.append(f"  - {name}: {desc}")
        if self.stale:
            lines.append(f"stale sources ({len(self.stale)}):")
            for rel, why in sorted(self.stale.items())[:10]:
                lines.append(f"  - {why}: {rel}")
            if len(self.stale) > 10:
                lines.append(f"  … and {len(self.stale) - 10} more")
        return "\n".join(lines)


def status(vault: Vault) -> CortexStatus:
    cdir = cortex_dir(vault)
    manifest = read_manifest(cdir)
    if manifest is None:
        return CortexStatus(vault_root=str(vault.root), cortex_path=str(cdir),
                            exists=False, fresh=False, note_count=0)
    fresh, stale = verify_fresh(vault, cdir, manifest=manifest)
    return CortexStatus(vault_root=str(vault.root), cortex_path=str(cdir),
                        exists=True, fresh=fresh,
                        note_count=len(manifest.get("sources", {})),
                        stale=stale, artifacts=manifest.get("artifacts", {}))


def clear(vault: Vault, *, everything: bool = False) -> Path:
    """Delete the DERIVED cortex artifacts. Loses speed, never memory (I1).

    bookkeeping.db is telemetry, NOT derived — it is preserved by default
    (a routine cache clear must not reset the salience/co-occurrence history
    the W3 proposals and W4 briefs feed on). `everything=True` wipes it too.
    """
    cdir = cortex_dir(vault)
    if not cdir.exists():
        return cdir
    if everything:
        shutil.rmtree(cdir)
        return cdir
    for child in cdir.iterdir():
        if child.name == "bookkeeping.db":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return cdir


class BridgeFilesUnruled(RuntimeError):
    """rebuild refused (fail-closed, audit H1): the bridge detector found
    files that are neither explicit-ruled nor quarantined. An unruled bridge
    file must BLOCK the build, not scroll past as a warning — a warning that
    only scrolls past can leave flagged files live and unreviewed for the
    whole window until someone reads the log. Override deliberately with
    allow_unruled_bridges=True (CLI: --allow-unruled-bridges)."""


def rebuild(vault: Vault, *, embedder=None, log=print,
            allow_unruled_bridges: bool = False) -> CortexStatus:
    """Rebuild the whole cortex from markdown. Everything derived; idempotent.

    One vault snapshot feeds the builders AND the manifest — hashing a
    re-walk would let an edit land between walks and stamp FRESH on an index
    that never saw it. `embedder=None` selects the real Ollama embedder;
    tests inject a deterministic fake.

    Fail-closed (audit H1): unruled bridge-detector hits ABORT the build
    (BridgeFilesUnruled, nothing written) unless allow_unruled_bridges=True,
    in which case the build proceeds with the loud per-file warnings.
    """
    cdir = cortex_dir(vault, create=True)
    artifacts: dict[str, dict] = {}

    try:
        from .dense import build_dense_index          # W2
        from .graphrep import build_graph_artifact    # W2
    except ImportError as e:
        raise RuntimeError(
            f"cortex builders unavailable ({e}); run `pip install -e .` in "
            "this environment (sqlite-vec/numpy are required since W2)") from e

    notes = vault.iter_notes_sorted()

    # audit R1b/H1 — build-time bridge detector: any note whose text
    # carries BOTH pseudonym and real-name vocabulary and is neither
    # explicitly ruled nor quarantined gets flagged LOUDLY, and by default
    # BLOCKS the build until a human rules each file in lane_map.yaml.
    from .dense import detect_bridge_files
    bridge_flags = detect_bridge_files(notes)
    for rel in bridge_flags:
        log(f"⚠ BRIDGE-FILE WARNING: {rel} matches BOTH pseudonym and "
            "real-name vocabulary but has no explicit lane ruling and is not "
            "quarantined — review it: it may deanonymise the case study. "
            "Add it to explicit_files or quarantined_files in lane_map.yaml.")
    if bridge_flags and not allow_unruled_bridges:
        raise BridgeFilesUnruled(
            f"rebuild refused (fail-closed): {len(bridge_flags)} unruled "
            "bridge file(s) found:\n  " + "\n  ".join(bridge_flags) +
            "\nRule each file in lane_map.yaml (explicit_files or "
            "quarantined_files), or rerun with --allow-unruled-bridges to "
            "proceed with warnings. Nothing was written.")

    artifacts["dense.sqlite3"] = build_dense_index(vault, cdir, embedder=embedder,
                                                   log=log, notes=notes)
    artifacts["graph.json"] = build_graph_artifact(vault, cdir, log=log, notes=notes)

    manifest = build_manifest(vault, artifacts, notes=notes)
    write_manifest(cdir, manifest)
    log(f"cortex rebuilt at {cdir} ({len(manifest['sources'])} sources)")
    # Truncation-proof detector summary (2026-07-06 incident: per-file
    # warnings emitted at the TOP of the build log were swallowed by a
    # `tail` in the operator's pipeline and 11 of 13 flags went unreported).
    # The count is restated as the FINAL build line so any tail of the log
    # carries it; per-file detail stays above.
    if bridge_flags:
        log(f"⚠ bridge detector: {len(bridge_flags)} file(s) flagged for "
            "review this build (see BRIDGE-FILE WARNING lines above)")
    else:
        log("bridge detector: 0 files flagged")
    return status(vault)


__all__ = ["cortex_dir", "cortex_exists", "vault_id", "content_hash",
           "source_map", "build_manifest", "write_manifest", "read_manifest",
           "stale_sources", "verify_fresh", "status", "clear", "rebuild",
           "BridgeFilesUnruled", "LaneConfigStale", "lane_config_stale",
           "LANE_CONFIG_STALE_REASON", "CortexStatus",
           "CORTEX_BUILDER_VERSION", "EMBED_MODEL", "EMBED_DIMS"]
