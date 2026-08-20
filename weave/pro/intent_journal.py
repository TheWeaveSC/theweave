"""Batch-apply intent journal — makes a mid-batch death VISIBLE (v1).

The consolidator's apply() patches several entity files in one loop with only
per-file backups. A death between two files leaves a silent partial apply —
the MemTxn paper's per-file-recovery failure mode (136/136 multi-key fault
runs unrecovered). v1 fix: write ONE intent record (full patch set + per-
target pre/post content hashes + status) BEFORE the loop, mark it completed
after a fully successful loop. `weave doctor` then flags any pending record
older than a few minutes and reports which targets were patched vs not, and
which backups to restore. Doctor REPORTS; it never auto-restores.

Records live under the cortex dir (derived-data territory, never the vault,
never synced): <cortex_dir>/intents/*.json.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..vault import Vault, content_hash

INTENTS_DIR_NAME = "intents"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"

# A pending record younger than this is (probably) an apply in flight, not a
# corpse. Doctor only flags records older than this.
STALE_AFTER_SECONDS = 300


@dataclass
class IntentTarget:
    rel_path: str        # vault-relative target file
    pre_hash: str        # content hash BEFORE the patch (weave.vault.content_hash)
    post_hash: str       # content hash the patch should produce
    backup_rel_path: str  # vault-relative backup written just before patching


@dataclass
class TargetState:
    """Doctor-side classification of one target of a stale pending intent."""
    rel_path: str
    state: str           # "patched" | "unpatched" | "diverged" | "missing"
    backup_rel_path: str


@dataclass
class StalePending:
    intent_path: Path
    created_at: str
    targets: list[TargetState] = field(default_factory=list)

    def patched(self) -> list[TargetState]:
        return [t for t in self.targets if t.state == "patched"]

    def unpatched(self) -> list[TargetState]:
        return [t for t in self.targets if t.state == "unpatched"]

    def all_patched(self) -> bool:
        """Every recorded target already shows its post-hash: the apply
        finished but the record was never finalized (e.g. mark_completed
        failed). NOT a partial apply — no restore needed, just journal
        cleanup. An empty/corrupt target list stays False (loud beats
        assumed-fine)."""
        return bool(self.targets) and all(t.state == "patched" for t in self.targets)


def intents_dir(vault: Vault, *, create: bool = False) -> Path:
    from .cortex import cortex_dir
    d = cortex_dir(vault, create=create) / INTENTS_DIR_NAME
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def write_intent(vault: Vault, targets: list[IntentTarget]) -> Path:
    """Persist ONE pending intent record for a whole batch. Called BEFORE the
    apply loop touches any file."""
    now = datetime.now(timezone.utc)
    record = {
        "intent_id": uuid.uuid4().hex[:12],
        "status": STATUS_PENDING,
        "created_at": now.isoformat(),
        "completed_at": None,
        "targets": [
            {
                "rel_path": t.rel_path,
                "pre_hash": t.pre_hash,
                "post_hash": t.post_hash,
                "backup_rel_path": t.backup_rel_path,
            }
            for t in targets
        ],
    }
    d = intents_dir(vault, create=True)
    path = d / f"intent-{now:%Y-%m-%d-%H%M%S}-{record['intent_id']}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def mark_completed(intent_path: Path) -> None:
    """Flip a pending record to completed (only after EVERY target patched)."""
    record = json.loads(intent_path.read_text(encoding="utf-8"))
    record["status"] = STATUS_COMPLETED
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    intent_path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _target_state(vault: Vault, entry: dict) -> TargetState:
    rel = entry["rel_path"]
    backup = entry.get("backup_rel_path", "")
    try:
        current = content_hash(vault.read_text(rel))
    except Exception:
        return TargetState(rel, "missing", backup)
    if current == entry["post_hash"]:
        return TargetState(rel, "patched", backup)
    if current == entry["pre_hash"]:
        return TargetState(rel, "unpatched", backup)
    return TargetState(rel, "diverged", backup)


def stale_pending(
    vault: Vault,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> list[StalePending]:
    """Every pending intent older than the threshold, with each target
    classified against the recorded pre/post hashes. Doctor's data source."""
    now = now or datetime.now(timezone.utc)
    d = intents_dir(vault)
    if not d.is_dir():
        return []
    out: list[StalePending] = []
    for path in sorted(d.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[weave intent-journal] unreadable record {path}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            continue
        if record.get("status") != STATUS_PENDING:
            continue
        try:
            created = datetime.fromisoformat(record["created_at"])
        except (KeyError, ValueError):
            created = None
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        # An unparseable timestamp counts as stale: better a false flag than
        # an invisible partial apply.
        if created is not None and (now - created).total_seconds() < stale_after_seconds:
            continue
        out.append(StalePending(
            intent_path=path,
            created_at=record.get("created_at", "?"),
            targets=[_target_state(vault, t) for t in record.get("targets", [])],
        ))
    return out
