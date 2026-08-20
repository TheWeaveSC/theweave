"""Cortex machine bookkeeping (W3) — retrieval log, salience, co-occurrence,
staleness → PROPOSAL reports.

I5 (single-writer) is structural here: this module has NO vault write path —
it only writes `bookkeeping.db` and `proposals/*.md` INSIDE the cortex dir.
The resident agent reads a proposal and applies what it accepts through the
normal write path. I4: we log ABOUT retrieval (verb, query, which notes) —
no session transcripts, no raw content.

bookkeeping.db is operational telemetry, not a derived artifact: it is
excluded from the manifest; deleting it loses stats, never memory.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..vault import Vault
from .cortex import cortex_dir, verify_fresh

BOOKKEEPING_DB = "bookkeeping.db"

# Proposal thresholds (start conservative; tuned by living with the reports)
COOCCUR_PROPOSE_MIN = 3      # recalled together this often -> propose a link
STALE_DAYS = 90              # high-salience + older valid_from -> staleness flag
SALIENCE_TOP_N = 15


def _open(cdir: Path) -> sqlite3.Connection:
    db = sqlite3.connect(cdir / BOOKKEEPING_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS retrieval_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, session TEXT NOT NULL, verb TEXT NOT NULL,
        query TEXT NOT NULL, results TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS salience(
        note_name TEXT PRIMARY KEY,
        recall_count INTEGER NOT NULL DEFAULT 0,
        last_recalled TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS cooccur(
        a TEXT NOT NULL, b TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (a, b))""")
    return db


def _query_key(query: str) -> str:
    """I4 discipline: recall queries are verbatim fragments of live session
    dialogue — storing them forever would accumulate an episodic trace inside
    the cortex, exactly the content class I4 keeps out. The log keeps a hash
    (enough to correlate repeats), never the text."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def log_retrieval(cdir: Path, verb: str, query: str, note_names: list[str],
                  *, session: str = "unknown", top_pairs: int = 5) -> None:
    """Record one retrieval + bump salience + co-occurrence. Never raises
    into the read path — callers wrap; this function keeps its own txn tight."""
    if not cdir.is_dir():
        return
    db = _open(cdir)
    try:
        db.execute(
            "INSERT INTO retrieval_log(ts, session, verb, query, results) "
            "VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), session, verb,
             _query_key(query), json.dumps(note_names)))
        today = date.today().isoformat()
        for name in note_names:
            db.execute(
                "INSERT INTO salience(note_name, recall_count, last_recalled) "
                "VALUES (?,1,?) ON CONFLICT(note_name) DO UPDATE SET "
                "recall_count = recall_count + 1, last_recalled = ?",
                (name, today, today))
        # co-occurrence over the head of the result list (the notes an agent
        # actually reads together), canonical pair order
        head = note_names[:top_pairs]
        for i in range(len(head)):
            for j in range(i + 1, len(head)):
                a, b = sorted((head[i], head[j]))
                db.execute(
                    "INSERT INTO cooccur(a, b, count) VALUES (?,?,1) "
                    "ON CONFLICT(a, b) DO UPDATE SET count = count + 1",
                    (a, b))
        db.commit()
    finally:
        db.close()


def stats(cdir: Path) -> dict:
    if not (cdir / BOOKKEEPING_DB).is_file():
        return {"retrievals": 0, "notes_tracked": 0, "pairs": 0}
    db = _open(cdir)
    try:
        return {
            "retrievals": db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0],
            "notes_tracked": db.execute("SELECT COUNT(*) FROM salience").fetchone()[0],
            "pairs": db.execute("SELECT COUNT(*) FROM cooccur").fetchone()[0],
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Proposal report (I5: markdown in the cortex; agent applies via write path)
# ---------------------------------------------------------------------------


def _existing_links(vault: Vault) -> set[tuple[str, str]]:
    """Undirected wikilink pairs currently in the LIVE vault. Deliberately
    NOT the graph artifact: proposals are judged against what the vault says
    now — a stale graph.json would re-propose links the agent already applied
    since the last rebuild."""
    notes = vault.iter_notes_sorted()
    names = {n.name for n in notes}
    pairs: set[tuple[str, str]] = set()
    for n in notes:
        for t in n.wikilinks():
            if t in names and t != n.name:
                pairs.add(tuple(sorted((n.name, t))))
    return pairs


def propose(vault: Vault, *, today: date | None = None) -> Path:
    """Generate a proposal report from accumulated bookkeeping. Writes ONLY
    inside the cortex (I5). Returns the report path."""
    today = today or date.today()
    cdir = cortex_dir(vault, create=True)
    db = _open(cdir)
    try:
        top_salience = db.execute(
            "SELECT note_name, recall_count, last_recalled FROM salience "
            "ORDER BY recall_count DESC, note_name LIMIT ?",
            (SALIENCE_TOP_N,)).fetchall()
        co_pairs = db.execute(
            "SELECT a, b, count FROM cooccur WHERE count >= ? "
            "ORDER BY count DESC, a, b", (COOCCUR_PROPOSE_MIN,)).fetchall()
        n_log = db.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    finally:
        db.close()

    linked = _existing_links(vault)
    link_proposals = [(a, b, c) for a, b, c in co_pairs
                      if (a, b) not in linked]

    # staleness: high-salience notes whose valid_from is old and still current
    notes_by_name = {n.name: n for n in vault.iter_notes()}
    stale_flags: list[tuple[str, int, str]] = []
    for name, count, _last in top_salience:
        n = notes_by_name.get(name)
        if n is None:
            continue
        vf = str(n.metadata.get("valid_from") or "")[:10]
        vu = n.metadata.get("valid_until")
        if not vf or vu:  # no date, or already closed
            continue
        try:
            age = (today - date.fromisoformat(vf)).days
        except ValueError:
            continue
        if age > STALE_DAYS:
            stale_flags.append((name, count, vf))

    lines: list[str] = []
    lines.append(f"# Cortex proposal report — {today.isoformat()}")
    lines.append("")
    lines.append("**PROPOSAL ONLY.** The cortex never writes the vault (I5). "
                 "Review each item and apply what you accept through the "
                 "normal write path; reject the rest by doing nothing.")
    lines.append(f"\nEvidence base: {n_log} logged retrievals.")
    if n_log < 10:
        lines.append("\n⚠ **THIN EVIDENCE** — fewer than 10 logged retrievals; "
                     "salience and co-occurrence below are noise, not signal. "
                     "Let a week of real usage accumulate before applying anything.")
    fresh, _stale = verify_fresh(vault, cdir)
    if not fresh:
        lines.append("\n⚠ cortex is STALE vs the live vault — link checks ran "
                     "against live markdown, but salience counters predate "
                     "recent edits; `weave cortex rebuild` recommended.")

    lines.append("\n## Wikilink proposals (co-recalled, not linked)")
    if link_proposals:
        for a, b, c in link_proposals:
            lines.append(f"- `[[{a}]]` ↔ `[[{b}]]` — recalled together {c}×, "
                         "no wikilink either way")
    else:
        lines.append("- (none met the threshold)")

    lines.append("\n## Staleness flags (high-salience, valid_from > "
                 f"{STALE_DAYS}d, still current)")
    if stale_flags:
        for name, count, vf in stale_flags:
            lines.append(f"- `{name}` — recalled {count}×, valid_from {vf}; "
                         "re-validate or supersede")
    else:
        lines.append("- (none)")

    lines.append("\n## Salience (top recalled notes)")
    lines.append("| note | recalls | last |")
    lines.append("|---|---|---|")
    for name, count, last in top_salience:
        lines.append(f"| {name} | {count} | {last} |")

    proposals_dir = cdir / "proposals"
    proposals_dir.mkdir(exist_ok=True)
    out = proposals_dir / f"proposal-{today.isoformat()}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


__all__ = ["log_retrieval", "stats", "propose", "BOOKKEEPING_DB",
           "COOCCUR_PROPOSE_MIN", "STALE_DAYS"]
