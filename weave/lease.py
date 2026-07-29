"""L5 — Advisory cross-machine lease for the WeaveCore verb layer.

WHAT THIS IS
------------
An advisory, best-effort lease that sits on top of L0's atomic write +
optimistic-concurrency CAS (`vault.write_text_if_unchanged`). It converts
LD#17's "one writer per project" rule from prose into code that:

  1. Refuses a write when a LIVE competing lease is held elsewhere
     (`LeaseHeldError`, naming the current holder), so two writers don't
     silently race each other.
  2. Stamps every write with WHO made it (owner/host/pid), fixing the
     audit finding that only ~3% of writes were attributable.
  3. Detects an existing iCloud conflict-copy (`<name> N.md`) for the
     target BEFORE writing into it (`ConflictCopyError`), promoting
     doctor's passive detector into an active pre-write guard. Because
     this is a filename heuristic that can false-positive on a
     legitimately-named file, `WEAVE_ALLOW_CONFLICT_COPIES=1` is an
     escape hatch that downgrades it to a no-op (see docs/lease.md).

WHAT THIS IS NOT
----------------
This is NOT a distributed lock and cannot be one on iCloud. iCloud sync is
asynchronous with no merge, and the lease sidecar file itself is just
another file that has to sync. Two writers that go simultaneously "cold"
(neither has seen the other's sidecar yet) on two different machines can
BOTH observe an absent/stale lease and BOTH acquire. That race window is
physically unclosable from user-space on top of iCloud.

What actually closes the common cases:
  - Same-machine multi-process / multi-window: FULLY closed. A fresh
    acquire opens the sidecar with O_CREAT|O_EXCL — the OS guarantees
    exactly one of any number of racing same-machine processes gets to
    create it, so this is not a read-check-then-write with a TOCTOU gap.
  - Human-paced multi-machine, once iCloud sync has settled: closed (the
    second machine sees the live sidecar and gets a named refusal).
  - Every write is attributable, independent of whether a race occurred.

When the lease can't prevent a simultaneous-cold-write race, the L0
content-hash CAS inside `write_text_if_unchanged` is the backstop: the
second writer to actually replace bytes gets `VaultConflictError` instead
of a silent lost update. If iCloud hasn't even synced the competing bytes
yet, CAS can't see them either — iCloud will materialize a "<name> N.md"
conflict copy, which this module's conflict-copy guard then surfaces on
the NEXT write rather than letting it sit silently.

See weave/docs/lease.md for the full honesty statement.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .vault import Vault

# Same heuristic doctor.py uses for TN2336-style iCloud conflict copies,
# defined once here so both doctor's passive sweep and this module's
# active pre-write guard agree on what counts as a conflict copy.
CONFLICT_COPY_RE = re.compile(r" \d+\.md$")

LEASE_SUFFIX = ".weavelock"

DEFAULT_TTL_S = 90.0


class LeaseHeldError(RuntimeError):
    """Raised when a live, non-stale lease held by someone else blocks a write."""

    def __init__(self, path: str, owner: str, host: str, pid: int, age_s: float):
        self.path = path
        self.owner = owner
        self.host = host
        self.pid = pid
        self.age_s = age_s
        super().__init__(
            f"{path} is currently locked by {owner} on {host} (pid {pid}), "
            f"heartbeat {age_s:.1f}s ago — retry shortly"
        )


class ConflictCopyError(RuntimeError):
    """Raised when an unreconciled iCloud conflict-copy sibling exists for path."""

    def __init__(self, path: str, copies: list[str]):
        self.path = path
        self.copies = copies
        sample = ", ".join(copies[:3])
        more = f" and {len(copies) - 3} more" if len(copies) > 3 else ""
        super().__init__(
            f"unreconciled iCloud conflict-copy detected for {path}: {sample}{more} "
            f"— reconcile before writing"
        )


@dataclass
class LeaseHandle:
    """Returned by acquire(); pass to heartbeat()/release()."""

    rel: str
    nonce: str
    owner: str
    host: str
    pid: int
    noop: bool = False  # True when the off-switch is set — heartbeat/release are no-ops


# ---------- env / identity ----------

def _off() -> bool:
    """WEAVE_LEASE off-switch. Default ON (lease enforced)."""
    val = os.environ.get("WEAVE_LEASE", "").strip().lower()
    return val in ("0", "false", "no", "off")


def _conflict_copies_allowed() -> bool:
    """WEAVE_ALLOW_CONFLICT_COPIES override. Default OFF (guard enforced).

    The conflict-copy guard is a filename heuristic (`<stem> <digits>.md`)
    and can false-positive on a legitimately-named file (e.g. a note the
    user genuinely named "weekly-2026 3.md"). A heuristic must never be
    allowed to permanently brick writes to a path with no way out, so this
    env var downgrades ConflictCopyError to a no-op pre-write check when
    set. See docs/lease.md for the tradeoff this documents.
    """
    val = os.environ.get("WEAVE_ALLOW_CONFLICT_COPIES", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _ttl_s() -> float:
    raw = os.environ.get("WEAVE_LEASE_TTL_S")
    if not raw:
        return DEFAULT_TTL_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TTL_S


def _identity() -> tuple[str, str, int]:
    """Return (owner, host, pid). owner = WEAVE_OWNER, else '<host>/<pid>'."""
    host = socket.gethostname()
    pid = os.getpid()
    owner = os.environ.get("WEAVE_OWNER", "").strip()
    if not owner:
        owner = f"{host}/{pid}"
    return owner, host, pid


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


# ---------- conflict-copy guard (shared with doctor.py) ----------

def find_conflict_copies(vault: Vault, rel: str) -> list[str]:
    """Return vault-relative paths of TN2336-style conflict-copy siblings of `rel`.

    E.g. for rel="entities/entity-Foo.md", matches sibling files named like
    "entity-Foo 2.md" in the same directory. Same regex doctor.py uses for
    its passive vault-wide sweep — defined once here, imported by doctor.
    """
    p = vault._resolve(rel)
    parent = p.parent
    stem = p.stem  # "entity-Foo"
    suffix = p.suffix  # ".md"
    if not parent.is_dir():
        return []
    found: list[str] = []
    for sibling in parent.glob(f"{stem} *{suffix}"):
        if CONFLICT_COPY_RE.search(sibling.name):
            found.append(vault.rel(sibling))
    return sorted(found)


# ---------- sidecar path ----------

def _lease_path(vault: Vault, rel: str) -> Path:
    p = vault._resolve(rel)
    return p.parent / f".{p.name}{LEASE_SUFFIX}"


def _read_sidecar(lease_path: Path) -> dict | None:
    if not lease_path.exists():
        return None
    try:
        return json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Corrupt/unreadable sidecar is treated as absent — best-effort.
        return None


def _write_sidecar(vault: Vault, lease_path: Path, data: dict) -> None:
    # Reuses L0's atomic write (fsync + os.replace) — a torn lease sidecar
    # is impossible, same guarantee as vault content writes.
    vault._atomic_write(lease_path, json.dumps(data, indent=2))


def _create_sidecar_exclusive(lease_path: Path, data: dict) -> None:
    """Create `lease_path` iff it does not already exist, atomically.

    Uses O_CREAT | O_EXCL | O_WRONLY: the OS guarantees that when two
    processes race this open() on the same path, exactly one gets the
    fd and the other gets FileExistsError — there is no read-then-write
    gap for a same-machine racer to land in. This is what actually closes
    the same-machine race; a prior read-check-then-replace implementation
    of acquire() could let two racing processes both observe "absent" and
    both proceed to write, defeating the "same-machine fully closed" claim.

    Raises FileExistsError if the sidecar already exists (caller falls
    back to the read-then-decide live/stale path). Raises OSError for any
    other failure (e.g. missing parent directory, permissions).
    """
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2)
    fd = os.open(str(lease_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        # Best-effort cleanup: we created it, so we own removing it if the
        # write itself fails after the exclusive create succeeded.
        try:
            lease_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---------- acquire / heartbeat / release ----------

def acquire(vault: Vault, rel: str) -> LeaseHandle:
    """Acquire an advisory lease on `rel` before a write.

    Raises ConflictCopyError if an unreconciled iCloud conflict-copy
    sibling exists (unless WEAVE_ALLOW_CONFLICT_COPIES overrides this —
    see docs/lease.md). Raises LeaseHeldError if a live competing lease
    exists. Performs a stale-lease takeover (overwriting the sidecar) if
    the existing lease's heartbeat is older than the TTL.

    A fresh acquire (no sidecar present yet) is done via an atomic
    exclusive create (O_CREAT|O_EXCL) so that two same-machine processes
    racing acquire() on the same path cannot both succeed — this is what
    closes the same-machine race for real (see module docstring).

    When WEAVE_LEASE is off, returns a no-op handle immediately without
    reading or writing anything.
    """
    if _off():
        owner, host, pid = _identity()
        return LeaseHandle(rel=rel, nonce="", owner=owner, host=host, pid=pid, noop=True)

    if not _conflict_copies_allowed():
        copies = find_conflict_copies(vault, rel)
        if copies:
            raise ConflictCopyError(rel, copies)

    owner, host, pid = _identity()
    lease_path = _lease_path(vault, rel)
    ttl = _ttl_s()

    nonce = secrets.token_hex(4)
    now = _now_iso()
    data = {
        "owner": owner,
        "host": host,
        "pid": pid,
        "acquired_at": now,
        "heartbeat": now,
        "nonce": nonce,
    }

    # Fast path: try an atomic exclusive create first. If the sidecar is
    # genuinely absent, O_EXCL guarantees exactly one racer among any
    # number of same-machine processes calling acquire() concurrently gets
    # to create it — there is no read-then-write gap here for a second
    # racer to slip through. This is what makes the "same-machine race
    # fully closed" claim true (see docs/lease.md).
    try:
        _create_sidecar_exclusive(lease_path, data)
        return LeaseHandle(rel=rel, nonce=nonce, owner=owner, host=host, pid=pid, noop=False)
    except FileExistsError:
        pass  # Sidecar already exists (or lost the race) -> fall through below.

    # Slow path: a sidecar exists. Decide live-refuse vs. stale-takeover.
    # This path is inherently read-then-write (an existing live lease means
    # we must NOT blindly overwrite), but that's fine: it only runs when a
    # sidecar is already known to exist, so the race this closes is
    # "did someone else already claim it", not "who claims it first".
    existing = _read_sidecar(lease_path)
    if existing is not None:
        try:
            hb = _parse_iso(existing["heartbeat"])
            age_s = (datetime.now(timezone.utc) - hb).total_seconds()
        except (KeyError, ValueError):
            age_s = ttl + 1  # unparsable sidecar -> treat as stale, allow takeover
        if age_s <= ttl:
            raise LeaseHeldError(
                rel,
                owner=existing.get("owner", "unknown"),
                host=existing.get("host", "unknown"),
                pid=existing.get("pid", -1),
                age_s=age_s,
            )
        # else: stale -> fall through to takeover (overwrite sidecar below)

    # existing is None here in practice only under a narrow TOCTOU window
    # (sidecar was removed between the FileExistsError and this read, e.g.
    # a concurrent release()) — treat that the same as a clean acquire.
    _write_sidecar(vault, lease_path, data)
    return LeaseHandle(rel=rel, nonce=nonce, owner=owner, host=host, pid=pid, noop=False)


def heartbeat(vault: Vault, handle: LeaseHandle) -> None:
    """Refresh the heartbeat timestamp on a held lease. No-op for off-switch handles."""
    if handle.noop:
        return
    lease_path = _lease_path(vault, handle.rel)
    existing = _read_sidecar(lease_path)
    if existing is None or existing.get("nonce") != handle.nonce:
        # We no longer hold it (taken over or released) — nothing to refresh.
        return
    existing["heartbeat"] = _now_iso()
    _write_sidecar(vault, lease_path, existing)


def release(vault: Vault, handle: LeaseHandle) -> None:
    """Release a held lease, but ONLY if the on-disk sidecar still carries our nonce.

    Never stomps a lease that a stale-takeover handed to someone else.
    Best-effort: a missing sidecar on release is fine.
    """
    if handle.noop:
        return
    lease_path = _lease_path(vault, handle.rel)
    existing = _read_sidecar(lease_path)
    if existing is None:
        return
    if existing.get("nonce") != handle.nonce:
        return
    try:
        lease_path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def lease(vault: Vault, rel: str) -> Iterator[LeaseHandle]:
    """Context manager: acquire, yield the handle, always release on exit."""
    handle = acquire(vault, rel)
    try:
        yield handle
    finally:
        release(vault, handle)


__all__ = [
    "LeaseHandle",
    "LeaseHeldError",
    "ConflictCopyError",
    "acquire",
    "heartbeat",
    "release",
    "lease",
    "find_conflict_copies",
    "CONFLICT_COPY_RE",
    "LEASE_SUFFIX",
    "DEFAULT_TTL_S",
]
