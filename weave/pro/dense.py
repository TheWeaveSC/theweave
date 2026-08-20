"""Dense chunk index for the cortex — nomic-embed-text -> sqlite-vec (W2).

Chunked per section over EVERY note dir except `_archive/`. The plan's first
cut excluded `sessions/` ("evidence reachable through the graph hop") — the
W0 harness PROVED that wrong: single-hop facts live in session notes, and
excluding them cost 0.50 vs 1.00 hit@8 on fixture single-hop. Measured >
assumed; sessions are in. Incremental by
per-file content hash: an unchanged file is never re-embedded.
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
from pathlib import Path

import sqlite_vec
import yaml

from ..vault import Note, Vault, content_hash
from .cortex import (CORTEX_BUILDER_VERSION, EMBED_DIMS,
                     LANE_CONFIG_STALE_REASON, LaneConfigStale,
                     lane_config_stale, read_manifest)

DENSE_DB = "dense.sqlite3"
# Path parts (dirs) excluded from the dense index. The GRAPH still covers
# every note, so excluded notes stay reachable via PPR.
DENSE_EXCLUDED_DIRS = frozenset({"_archive"})
MAX_CHUNK_CHARS = 2000

_SECTION_RE = re.compile(r"^#{2,3}\s+(.*)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Lane firewall — lane resolution (lane_map.yaml lives at the repo root,
# never in the vault; it names files, never quotes content).
# ---------------------------------------------------------------------------

LANES = ("thesis", "operational", "neutral")
LANE_MAP_FILE = Path(__file__).resolve().parents[2] / "lane_map.yaml"

_lane_map_cache: tuple[tuple[int, int], dict] | None = None


def load_lane_map(path: Path | None = None) -> dict:
    """Parse + normalize lane_map.yaml. Cached on (mtime, size); explicit
    `path` (tests) bypasses the cache."""
    global _lane_map_cache
    p = Path(path) if path else LANE_MAP_FILE
    st = p.stat()
    sig = (st.st_mtime_ns, st.st_size)
    if path is None and _lane_map_cache and _lane_map_cache[0] == sig:
        return _lane_map_cache[1]
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    lanes_raw = raw.get("lanes", {})
    lm = {
        "default_lane": raw.get("default_lane", "operational"),
        "explicit_rel": {}, "explicit_base": {}, "globs": {}, "prefixes": {},
        "dense_excluded": frozenset(raw.get("dense_excluded_files") or []),
        "quarantined": frozenset(raw.get("quarantined_files") or []),
        "bridge_vocab": raw.get("bridge_vocab") or {},
        "learninglayer": raw.get("learninglayer") or {},
    }
    for lane in LANES:
        spec = lanes_raw.get(lane) or {}
        explicit = list(spec.get("explicit_files") or [])
        lm["explicit_rel"][lane] = frozenset(explicit)
        # basename matching = wiki mirrors inherit their source's lane 1:1
        lm["explicit_base"][lane] = frozenset(Path(e).name for e in explicit)
        lm["globs"][lane] = [g.lower() for g in (spec.get("filename_globs") or [])]
        lm["prefixes"][lane] = list(spec.get("dir_prefixes") or [])
    if lm["default_lane"] not in LANES:
        raise ValueError(f"lane_map: bad default_lane {lm['default_lane']!r}")
    return lm if path else _cache_lane_map(sig, lm)


def _cache_lane_map(sig, lm) -> dict:
    global _lane_map_cache
    _lane_map_cache = (sig, lm)
    return lm


def lane_map_hash() -> str:
    """Content hash of lane_map.yaml (audit R2). Hashed into the cortex
    manifest at build time; recall refuses to serve a cache whose lane config
    no longer matches — lane-config drift is a correctness failure, not a
    staleness banner."""
    return content_hash(LANE_MAP_FILE.read_text(encoding="utf-8"))


_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def lane_of(note: Note, lane_map: dict | None = None) -> str:
    """Resolve a note's lane. Resolution order (the firewall spec):
    explicit_files > filename_globs > longest dir_prefix >
    LearningLayer vocabulary rule > default_lane."""
    lm = lane_map or load_lane_map()
    rel = note.rel_path
    base = Path(rel).name
    # 1. explicit rulings (rel_path, then basename for wiki mirrors)
    for lane in LANES:
        if rel in lm["explicit_rel"][lane]:
            return lane
    for lane in LANES:
        if base in lm["explicit_base"][lane]:
            return lane
    # 2. filename globs, case-insensitive; LANES order means thesis wins a tie
    low = base.lower()
    for lane in LANES:
        if any(fnmatch.fnmatchcase(low, pat) for pat in lm["globs"][lane]):
            return lane
    # 3. longest dir prefix
    best_len, best_lane = 0, None
    for lane in LANES:
        for pref in lm["prefixes"][lane]:
            if rel.startswith(pref) and len(pref) > best_len:
                best_len, best_lane = len(pref), lane
    if best_lane:
        return best_lane
    # 4. LearningLayer both-lane signals: majority vocabulary count,
    # ties -> operational (filename tags were already handled by the globs)
    ll = lm["learninglayer"]
    if ll and rel.startswith(ll.get("dir_prefix", "\x00")):
        text = note.raw_text.lower()
        counts: dict[str, int] = {}
        for lane, words in (ll.get("vocab") or {}).items():
            total = 0
            for w in words:
                pat = _WORD_RE_CACHE.get(w)
                if pat is None:
                    pat = _WORD_RE_CACHE.setdefault(
                        w, re.compile(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])"))
                total += len(pat.findall(text))
            counts[lane] = total
        if counts.get("thesis", 0) > counts.get("operational", 0):
            return "thesis"
        return "operational"
    # 5. default
    return lm["default_lane"]


def dense_excluded_files(lane_map: dict | None = None) -> frozenset[str]:
    """Hub files excluded from the dense index entirely (and never PPR-seeded
    — recall enforces that side). Exact rel_path match."""
    lm = lane_map or load_lane_map()
    return lm["dense_excluded"]


def quarantined_files(lane_map: dict | None = None) -> frozenset[str]:
    """Bridge files carrying the pseudonym<->real-name crosswalk (audit
    R1): never embedded, never PPR-seeded, never returned from recall in ANY
    lane. Exact rel_path match. The vault files themselves stay untouched."""
    lm = lane_map or load_lane_map()
    return lm["quarantined"]


def unretrievable_files(lane_map: dict | None = None) -> frozenset[str]:
    """Hub exclusions ∪ quarantine — the full never-seed/never-return set."""
    lm = lane_map or load_lane_map()
    return lm["dense_excluded"] | lm["quarantined"]


def dense_eligible(note: Note, lane_map: dict | None = None) -> bool:
    parts = Path(note.rel_path).parts[:-1]
    if any(p in DENSE_EXCLUDED_DIRS for p in parts):
        return False
    return note.rel_path not in unretrievable_files(lane_map)


def detect_bridge_files(notes: list[Note], lane_map: dict | None = None
                        ) -> list[str]:
    """Build-time bridge detector (audit R1b). Returns rel_paths of notes
    whose text matches BOTH bridge vocab lists (pseudonym + real-name) and
    are neither explicitly ruled (explicit_files, any lane) nor quarantined.
    Case-insensitive whole-word/phrase match over the FULL file text
    (frontmatter included — pseudonym fields live there too). The caller must
    warn LOUDLY for every hit; false positives are acceptable, silence is not.
    """
    lm = lane_map or load_lane_map()
    bv = lm["bridge_vocab"]
    pseud = [t for t in (bv.get("pseudonym_vocab") or [])]
    real = [t for t in (bv.get("realname_vocab") or [])]
    if not pseud or not real:
        return []

    def _pat(term: str) -> re.Pattern:
        key = f"bridge::{term}"
        pat = _WORD_RE_CACHE.get(key)
        if pat is None:
            pat = _WORD_RE_CACHE.setdefault(key, re.compile(
                rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"))
        return pat

    ruled: set[str] = set()
    for lane in LANES:
        ruled |= lm["explicit_rel"][lane]
    skip = ruled | lm["quarantined"]

    flagged: list[str] = []
    for n in notes:
        if n.rel_path in skip:
            continue
        text = n.raw_text.lower()
        if any(_pat(t).search(text) for t in pseud) and \
           any(_pat(t).search(text) for t in real):
            flagged.append(n.rel_path)
    return sorted(flagged)


def chunk_note(note: Note) -> list[tuple[str, str]]:
    """Split a note body per section. Returns [(section, text)].

    Every chunk text is prefixed with the note name + section so the
    embedding carries WHICH thing the passage is about (entity names are the
    strongest retrieval keys this vault has).
    """
    body = note.content.strip()
    chunks: list[tuple[str, str]] = []

    spans = list(_SECTION_RE.finditer(body))
    head = body[: spans[0].start()] if spans else body
    if head.strip():
        chunks.append(("_head", head.strip()))
    for i, m in enumerate(spans):
        end = spans[i + 1].start() if i + 1 < len(spans) else len(body)
        text = body[m.end():end].strip()
        if text:
            chunks.append((m.group(1).strip(), text))

    # Frontmatter carries load-bearing facts (status lines, one-liners) —
    # fold scalar values into a single chunk.
    fm_bits = [f"{k}: {v}" for k, v in sorted(note.metadata.items())
               if isinstance(v, (str, int, float)) and str(v).strip()]
    if fm_bits:
        chunks.append(("_frontmatter", "\n".join(fm_bits)))

    out: list[tuple[str, str]] = []
    for section, text in chunks:
        for piece in _split_long(text):
            out.append((section, f"{note.name} — {section}\n{piece}"))
    return out


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur, n = [], [], 0
    for para in text.split("\n\n"):
        if n + len(para) > limit and cur:
            parts.append("\n\n".join(cur)); cur, n = [], 0
        cur.append(para); n += len(para) + 2
    if cur:
        parts.append("\n\n".join(cur))
    # Hard bound: a single paragraph over the limit (pasted log, minified
    # blob) must still be sliced — the embedder truncates silently past its
    # window, which would make the tail unretrievable with no error.
    out: list[str] = []
    for p in parts:
        if len(p) <= limit:
            out.append(p)
        else:
            out.extend(p[i:i + limit] for i in range(0, len(p), limit))
    return out


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def open_dense_db(cdir: Path) -> sqlite3.Connection:
    db = sqlite3.connect(cdir / DENSE_DB)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    # Lane firewall schema migration: a pre-lane chunks table (no `lane`
    # column) cannot be lane-filtered — drop and let the builder re-embed.
    # Write path only; dense_search opens read-only and never migrates.
    legacy = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
    ).fetchone()
    if legacy:
        cols = {r[1] for r in db.execute("PRAGMA table_info(chunks)")}
        if "lane" not in cols:
            db.execute("DROP TABLE chunks")
            db.execute("DROP TABLE IF EXISTS vec_chunks")
            db.commit()
    db.execute("""CREATE TABLE IF NOT EXISTS chunks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_name TEXT NOT NULL, rel_path TEXT NOT NULL,
        section TEXT NOT NULL, text TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        lane TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_rel ON chunks(rel_path)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_lane ON chunks(lane)")
    db.execute(f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
        embedding float[{EMBED_DIMS}] distance_metric=cosine)""")
    return db


def build_dense_index(vault: Vault, cdir: Path, *, embedder=None, log=print,
                      notes: list[Note] | None = None) -> dict:
    """(Re)build the dense index incrementally. Returns the artifact meta —
    deterministic (counts + versions, no clocks). Pass `notes` (the rebuild
    snapshot) so index and manifest hash the same bytes."""
    if embedder is None:
        from .embedder import default_embedder
        embedder = default_embedder()

    lane_map = load_lane_map()
    if notes is None:
        notes = vault.iter_notes_sorted()
    notes = [n for n in notes if dense_eligible(n, lane_map)]
    current = {n.rel_path: content_hash(n.raw_text) for n in notes}

    db = open_dense_db(cdir)
    try:
        recorded = dict(db.execute(
            "SELECT rel_path, file_hash FROM chunks GROUP BY rel_path"))
        stale_paths = ({p for p, h in current.items() if recorded.get(p) != h}
                       | (set(recorded) - set(current)))

        if stale_paths:
            # drop chunks (and their vectors) for stale files
            for rel in sorted(stale_paths):
                ids = [r[0] for r in db.execute(
                    "SELECT id FROM chunks WHERE rel_path = ?", (rel,))]
                if ids:
                    ph = ",".join("?" * len(ids))
                    db.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({ph})", ids)
                    db.execute(f"DELETE FROM chunks WHERE id IN ({ph})", ids)

            to_embed: list[tuple[Note, str, str]] = []
            for n in notes:
                if n.rel_path in stale_paths:
                    for section, text in chunk_note(n):
                        to_embed.append((n, section, text))
            if to_embed:
                log(f"dense: embedding {len(to_embed)} chunks "
                    f"from {len(stale_paths & set(current))} files "
                    f"({embedder.name})")
            BATCH = 32
            for i in range(0, len(to_embed), BATCH):
                batch = to_embed[i:i + BATCH]
                vecs = embedder.embed([t for _, _, t in batch])
                for (n, section, text), vec in zip(batch, vecs):
                    cur = db.execute(
                        "INSERT INTO chunks(note_name, rel_path, section, text, "
                        "file_hash, lane) VALUES (?,?,?,?,?,?)",
                        (n.name, n.rel_path, section, text,
                         current[n.rel_path], lane_of(n, lane_map)))
                    db.execute(
                        "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                        (cur.lastrowid, sqlite_vec.serialize_float32(vec)))
            db.commit()

        n_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"kind": "dense-index", "files": len(current), "chunks": n_chunks,
                "model": embedder.name, "dims": EMBED_DIMS,
                "builder": CORTEX_BUILDER_VERSION,
                "excluded_dirs": sorted(DENSE_EXCLUDED_DIRS),
                "excluded_files": sorted(dense_excluded_files(lane_map))}
    finally:
        db.close()


class DenseIndexMissing(RuntimeError):
    """dense.sqlite3 absent — the read path must degrade, never fabricate."""


def dense_search(cdir: Path, query_vec: list[float], m: int = 24,
                 lane: str | None = None) -> list[tuple[str, str, str, float]]:
    """Top-m chunks by cosine distance. Returns (note_name, rel_path,
    section, similarity) — similarity = 1 - cosine_distance.

    `lane`: lane firewall filter point 1 — only chunks whose lane is the
    requested lane OR neutral are returned. None = unfiltered (lane-blind
    legacy callers only; recall always passes a lane).

    Opens READ-ONLY: a read must never create an empty index (a partial
    cortex would then 'answer' with zero recall while looking healthy).

    HASH GATE AT THE DATA SEAM (audit H2): the lane-config freshness
    check lives HERE so ANY caller — recall(), bench, future skills/CLI —
    inherits the LaneConfigStale refusal instead of silently reading chunks
    whose lane column was computed under an older lane_map.yaml. A missing
    manifest fails closed for the same reason."""
    db_path = cdir / DENSE_DB
    if not db_path.is_file():
        raise DenseIndexMissing(f"{db_path} missing — run `weave cortex rebuild`")
    manifest = read_manifest(cdir)
    if manifest is None:
        raise LaneConfigStale(
            "cortex manifest missing — lane provenance of this index is "
            "unverifiable; rebuild required (`weave cortex rebuild`)")
    if lane_config_stale(manifest):
        raise LaneConfigStale(LANE_CONFIG_STALE_REASON)
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    try:
        if lane is None:
            rows = db.execute(
                """SELECT c.note_name, c.rel_path, c.section, v.distance
                   FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
                   WHERE v.embedding MATCH ? AND v.k = ?
                   ORDER BY v.distance""",
                (sqlite_vec.serialize_float32(query_vec), m)).fetchall()
        else:
            if lane not in LANES:
                raise ValueError(f"unknown lane {lane!r} (expected one of {LANES})")
            # KNN applies k BEFORE the lane predicate — over-fetch so a lane
            # whose chunks are outnumbered near the query still gets ~m seeds,
            # then filter + trim. 4x is a heuristic bound, not a guarantee.
            rows = db.execute(
                """SELECT c.note_name, c.rel_path, c.section, v.distance
                   FROM vec_chunks v JOIN chunks c ON c.id = v.rowid
                   WHERE v.embedding MATCH ? AND v.k = ?
                     AND c.lane IN (?, 'neutral')
                   ORDER BY v.distance LIMIT ?""",
                (sqlite_vec.serialize_float32(query_vec), min(m * 4, 256),
                 lane, m)).fetchall()
        return [(n, r, s, 1.0 - d) for n, r, s, d in rows]
    finally:
        db.close()


__all__ = ["build_dense_index", "dense_search", "open_dense_db", "chunk_note",
           "dense_eligible", "DenseIndexMissing", "DENSE_DB", "DENSE_EXCLUDED_DIRS",
           "LANES", "LANE_MAP_FILE", "load_lane_map", "lane_of",
           "dense_excluded_files", "quarantined_files", "unretrievable_files",
           "detect_bridge_files", "lane_map_hash"]
