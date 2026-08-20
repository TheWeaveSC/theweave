"""Sleep-time consolidator — Pattern 4.

Runs periodically (default dry-run): scan recent session notes, for each
touched entity propose a "Recent activity" patch, then reflect over
LearningLayer signals to synthesise higher-order themes.

Outputs:
  - `--dry-run` (default): a single consolidation report at
    `_archive/consolidation-YYYY-MM-DD-HHMM.md`. No entity files patched.
  - `--apply`: writes the report AND patches each touched entity file
    (saves a backup of the prior version to `_archive/<name>-YYYY-MM-DD-HHMM.md`).

Inspired by:
  - Letta's sleep-time-compute (background memory-edit agent)
  - A-MEM's neighbour-update on link creation (we batch this nightly instead)
  - Hindsight's reflect step (synthesise atomic facts into patterns)
"""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..vault import Note, Vault, WIKILINK_RE
from .bitemporal import BiTemporalResolver
from .llm import get_llm, is_mock

# Type allowlist for LearningLayer signal notes. Resolved against the real
# vaults: every signal file carries `type: learning-signals` (exclusive; the
# literal `agent-learning` does not appear in any vault). Locked to this single
# type — widen here if a new signal type is ever introduced.
SIGNAL_TYPES: frozenset[str] = frozenset({"learning-signals"})


def signal_files(vault: Vault) -> list[Note]:
    """Public: every LearningLayer note whose type is in SIGNAL_TYPES.

    Sorted by rel_path: iter_notes() inherits filesystem (rglob) order, which
    is not canonical across machines — byte-stable consumers (hydrate) need a
    deterministic order.
    """
    return sorted(
        (n for n in vault.iter_notes()
         if _path_contains_dir(n.rel_path, "LearningLayer")
         and n.metadata.get("type") in SIGNAL_TYPES),
        key=lambda n: n.rel_path,
    )


def extract_signal_lines(signal_files: list[Note]) -> list[str]:
    """Public: pull the `- ...` bullet lines out of a set of signal notes."""
    signals: list[str] = []
    for n in signal_files:
        for ln in n.content.splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                signals.append(ln[2:].strip())
    return signals


@dataclass
class EntityPatch:
    entity_name: str
    entity_path: str
    referencing_sessions: list[Note] = field(default_factory=list)
    proposed_block: str = ""


@dataclass
class ConsolidationReport:
    generated_at: datetime
    is_mock: bool
    window_days: int
    sessions_scanned: list[Note]
    patches: list[EntityPatch]
    reflect_output: str
    signal_files_scanned: list[Note]

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# Weave Consolidation Report — {self.generated_at:%Y-%m-%d %H:%M}")
        lines.append("")
        mode = "MOCK (offline)" if self.is_mock else "Claude (live)"
        lines.append(f"**Mode:** {mode}  |  **Window:** last {self.window_days} days")
        lines.append(f"**Sessions scanned:** {len(self.sessions_scanned)}")
        lines.append(f"**Entity patches proposed:** {len(self.patches)}")
        lines.append(f"**Signal files reflected:** {len(self.signal_files_scanned)}")
        lines.append("")
        lines.append("## Reflect synthesis")
        lines.append("")
        lines.append(self.reflect_output.strip() or "(no signals)")
        lines.append("")
        lines.append("## Per-entity patches")
        lines.append("")
        if not self.patches:
            lines.append("_(none)_")
        for patch in self.patches:
            lines.append(f"### `{patch.entity_name}`  → `{patch.entity_path}`")
            sess = ", ".join(f"`{n.name}`" for n in patch.referencing_sessions) or "(none)"
            lines.append(f"  - Referencing sessions: {sess}")
            lines.append("")
            lines.append("```markdown")
            lines.append(patch.proposed_block.rstrip())
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


class Consolidator:
    def __init__(self, vault: Vault, *, window_days: int = 14):
        self.vault = vault
        self.window_days = window_days
        self.resolver = BiTemporalResolver(vault)

    # ---------- scan ----------

    def _recent_sessions(self, today: date) -> list[Note]:
        cutoff = today - timedelta(days=self.window_days)
        recent: list[tuple[date, Note]] = []
        for note in self.vault.iter_notes():
            if not _path_contains_dir(note.rel_path, "sessions"):
                continue
            d = self._note_date(note)
            if d is None:
                continue
            if d >= cutoff:
                recent.append((d, note))
        recent.sort(key=lambda pair: (pair[0], pair[1].rel_path))
        return [n for _, n in recent]

    def _note_date(self, note: Note) -> date | None:
        v = note.metadata.get("date")
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        # fall back to filename pattern session-YYYY-MM-DD-...
        m = re.match(r"session-(\d{4}-\d{2}-\d{2})", note.name)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                return None
        return None

    def _touched_entities(self, session: Note) -> list[str]:
        """Resolve touched entity names from a session, hop through supersession."""
        names: list[str] = []
        seen: set[str] = set()
        # frontmatter `touches:` + body wikilinks
        for link in session.wikilinks():
            res = self.resolver.resolve(link)
            target = res.current.name if res.current else link
            if target not in seen and not target.startswith(("session-", "signals-")):
                names.append(target)
                seen.add(target)
        return names

    def _signal_files(self) -> list[Note]:
        """Backward-compat alias for the public module-level signal_files()."""
        return signal_files(self.vault)

    # ---------- build report ----------

    def build_report(self, *, today: date | None = None) -> ConsolidationReport:
        today = today or date.today()
        sessions = self._recent_sessions(today)
        entity_to_sessions: dict[str, list[Note]] = defaultdict(list)
        for sess in sessions:
            for ent in self._touched_entities(sess):
                entity_to_sessions[ent].append(sess)

        patches: list[EntityPatch] = []
        for ent_name, sess_list in entity_to_sessions.items():
            note = self.vault.find_note_by_name(ent_name)
            if note is None:
                continue
            block = self._render_activity_block(sess_list, today)
            patches.append(EntityPatch(
                entity_name=ent_name,
                entity_path=note.rel_path,
                referencing_sessions=sess_list,
                proposed_block=block,
            ))

        # Reflect over signal files
        signal_files = self._signal_files()
        raw_signals = self._extract_signal_lines(signal_files)
        llm = get_llm()
        reflect_text = llm.reflect_signals(raw_signals)

        return ConsolidationReport(
            generated_at=datetime.now(),
            is_mock=is_mock(),
            window_days=self.window_days,
            sessions_scanned=sessions,
            patches=patches,
            reflect_output=reflect_text,
            signal_files_scanned=signal_files,
        )

    @staticmethod
    def _render_activity_block(sessions: list[Note], today: date) -> str:
        lines = [f"## Recent activity (as of {today:%Y-%m-%d})", ""]
        for sess in sessions:
            d = sess.metadata.get("date", "?")
            # one-line excerpt: first heading or first line of body
            content_lines = [ln.strip() for ln in sess.content.splitlines() if ln.strip()]
            headline = next((ln.lstrip("# ").strip() for ln in content_lines if ln.startswith("#")), "")
            if not headline and content_lines:
                headline = content_lines[0][:80]
            lines.append(f"- {d} — [[{sess.name}]] — {headline}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extract_signal_lines(files: list[Note]) -> list[str]:
        """Backward-compat alias for the public module-level extract_signal_lines()."""
        return extract_signal_lines(files)

    # ---------- apply ----------

    def apply(self, report: ConsolidationReport) -> list[str]:
        """Patch entity files with backups. Returns list of patched paths.

        Multi-file batch safety (v1): the FULL patch set (with pre/post
        content hashes) is journalled as ONE pending intent record under the
        cortex dir before the loop touches any file, and marked completed
        only after every target is patched. A mid-batch death leaves the
        record pending — `weave doctor` flags it and lists patched vs
        unpatched targets and the backups to restore.
        """
        from ..vault import content_hash
        from . import intent_journal

        patched: list[str] = []
        stamp = report.generated_at.strftime("%Y-%m-%d-%H%M")
        archive_dir = self.vault.root / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Pre-compute every target's patched content so the intent record can
        # carry pre/post hashes for the WHOLE batch up front.
        planned: list[tuple[EntityPatch, Path, Path, str]] = []
        targets: list[intent_journal.IntentTarget] = []
        for patch in report.patches:
            ent_path = self.vault.root / patch.entity_path
            if not ent_path.exists():
                continue
            backup = archive_dir / f"{Path(patch.entity_path).stem}-{stamp}.md"
            text = ent_path.read_text(encoding="utf-8")
            new_text = _replace_or_append_section(text, "## Recent activity", patch.proposed_block)
            planned.append((patch, ent_path, backup, new_text))
            targets.append(intent_journal.IntentTarget(
                rel_path=patch.entity_path,
                pre_hash=content_hash(text),
                post_hash=content_hash(new_text),
                backup_rel_path=self.vault.rel(backup),
            ))

        # Journal the intent BEFORE any file is touched. Fail-open: a broken
        # cortex dir must not block consolidation — it only costs the safety
        # net, loudly.
        intent_path: Path | None = None
        if targets:
            try:
                intent_path = intent_journal.write_intent(self.vault, targets)
            except Exception as e:
                import sys
                print(f"[weave consolidator] intent journal unavailable "
                      f"({type(e).__name__}: {e}) — applying WITHOUT "
                      f"mid-batch crash detection.", file=sys.stderr)

        for patch, ent_path, backup, new_text in planned:
            shutil.copy2(ent_path, backup)
            ent_path.write_text(new_text, encoding="utf-8")
            patched.append(patch.entity_path)

        if intent_path is not None:
            # Same fail-open contract as write_intent: after a fully
            # successful loop, a journal that turned unwritable must not make
            # apply() raise (losing the return value and skipping the report
            # write below). The stale pending record it leaves behind shows
            # every target patched; doctor words that as "journal not
            # finalized" rather than a partial apply.
            try:
                intent_journal.mark_completed(intent_path)
            except Exception as e:
                import sys
                print(f"[weave consolidator] could not finalize intent record "
                      f"{intent_path} ({type(e).__name__}: {e}) — apply "
                      f"succeeded; doctor will report it as not finalized.",
                      file=sys.stderr)

        # write the report
        report_path = archive_dir / f"consolidation-{stamp}.md"
        report_path.write_text(report.to_markdown(), encoding="utf-8")
        return patched

    def write_report_only(self, report: ConsolidationReport) -> str:
        stamp = report.generated_at.strftime("%Y-%m-%d-%H%M")
        archive_dir = self.vault.root / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        path = archive_dir / f"consolidation-{stamp}.md"
        path.write_text(report.to_markdown(), encoding="utf-8")
        return str(path.relative_to(self.vault.root))


def _path_contains_dir(rel_path: str, name: str) -> bool:
    # Match `<name>/` anywhere in the relative path (works for both the
    # seed-vault flat layout and the canonical `<VaultName>Vault/<name>/` layout).
    return f"/{name}/" in f"/{rel_path}"


_SECTION_RE = re.compile(r"^(## Recent activity[^\n]*\n.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _replace_or_append_section(text: str, heading: str, block: str) -> str:
    """Replace an existing block under `heading`, or append it at the end."""
    block = block.rstrip() + "\n"
    if _SECTION_RE.search(text):
        return _SECTION_RE.sub(block, text, count=1)
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + block
