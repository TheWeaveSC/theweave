# L5 — Advisory cross-machine lease

`weave/lease.py`, wired into the write verbs in `weave/core.py`
(`create`, `str_replace`, `insert`, `delete`). `view` never leases.

This document states plainly what the lease does and does not guarantee.
Read it before assuming this closes every race — it closes the common
ones, not all of them, and it cannot on iCloud.

## Why this exists

Arch-audit finding (2026-06-30): two writers on the same iCloud-synced
vault (Air + Mini, or two Claude windows on one machine) can lost-update
each other. L0's `write_text_if_unchanged` CAS only compares **local**
bytes — a not-yet-synced remote write is invisible to it. LD#17's
"one-writer-per-project lease" was pure prose: nothing in code enforced
it, and an audit found only ~3% of writes tagged an owner.

## What it does

Before a write verb touches bytes, it:

1. **Checks for an iCloud conflict copy.** If a `<name> N.md` sibling of
   the target already exists (the TN2336 pattern), the verb raises
   `ConflictCopyError` naming the file(s) — before writing anything. This
   check is skipped entirely when `WEAVE_ALLOW_CONFLICT_COPIES` is set
   (see "Conflict-copy hard-block and its override" below).
2. **Acquires a sidecar lease** named `.<name>.md.weavelock`, sitting next
   to the target file. It records `owner`, `host`, `pid`,
   `acquired_at`, `heartbeat`, and a random `nonce` identifying this
   specific acquisition.
   - **Fresh acquire (no sidecar yet):** the sidecar is created with
     `os.open(..., O_CREAT | O_EXCL | O_WRONLY)` — an atomic exclusive
     create. The OS guarantees that when multiple same-machine processes
     race this call on the same path, exactly one gets the file descriptor
     and every other racer gets `FileExistsError` immediately, with no
     read-then-write gap in between for a second racer to slip through.
   - If the exclusive create loses the race (or a sidecar already exists
     for another reason), acquire falls back to reading the sidecar: a
     live lease (heartbeat newer than the TTL) that isn't ours raises
     `LeaseHeldError`, naming the current holder (owner/host/pid/age); a
     stale lease is taken over (sidecar rewritten with our nonce via the
     ordinary tempfile+replace atomic write).
3. **Performs the L0 write** (atomic write + CAS where applicable) with
   the lease held.
4. **Releases** the lease afterward — but only if the on-disk sidecar
   still carries our nonce, so a takeover is never stomped by the writer
   it took the lease from.

The lease sidecar file is always written atomically — either via the
exclusive-create fast path above (fresh acquire) or through the same
`_atomic_write` tempfile+`os.replace` primitive vault content writes use
(takeover of a stale lease) — so a torn lease file is impossible on either
path.

Because the sidecar is dot-prefixed, it is already excluded from
`iter_notes()`, the doctor sweep, and the wikilink graph — all three skip
dotted path parts (the same rule that already hides `.trash/`). No new
sweep/graph plumbing was needed.

## What it guarantees (real, valuable)

- **Same-machine multi-process / multi-window: fully closed, because of
  O_EXCL.** A fresh acquire opens the sidecar with
  `O_CREAT | O_EXCL | O_WRONLY`, an atomic exclusive create the OS
  enforces — not a read-check-then-write. Two processes on one Mac racing
  `acquire()` on the same path cannot both create the sidecar: exactly one
  wins, the other gets `FileExistsError` and falls into the normal
  live-lease path, raising `LeaseHeldError`. (An earlier version of this
  module did read-check-then-write here, which left a same-machine race
  window open despite the "fully closed" claim; O_EXCL is what actually
  closes it.) This is the everyday case (two Claude windows open on Air).
- **Human-paced multi-machine, once iCloud has synced: closed.** Once the
  sidecar has propagated from Air to Mini (or vice versa), the second
  machine sees the live lease and gets a `LeaseHeldError` naming the
  holder, instead of silently racing.
- **Every write is now attributable.** Owner/host/pid/timestamp is
  stamped on the lease regardless of whether a race occurred — this
  directly fixes the "3% of writes tagged an owner" finding.
- **Writes never land on top of an already-detected iCloud conflict
  copy.** `ConflictCopyError` fires before any bytes are touched.
- **No torn lease files**, and a crashed holder's lease self-heals after
  the TTL via takeover.

## What it does NOT guarantee (the ceiling)

- **This is not a distributed lock, and cannot be one on top of iCloud.**
  iCloud sync is asynchronous with no merge, and the lease sidecar file
  itself is just another file that has to sync. Two writers that go
  **simultaneously cold** — neither has seen the other's sidecar yet, on
  two different machines — can **both** acquire before either sidecar
  propagates. That race window is physically unclosable from user-space
  on iCloud. This layer does not pretend otherwise.
- **The CAS backstop, and its own limit.** In that simultaneous-cold-write
  case, L0's content-hash CAS (`write_text_if_unchanged`) is the
  last-line defense: whoever replaces second and finds the hash changed
  gets `VaultConflictError` instead of a silent lost update. But if
  iCloud hasn't synced the other writer's bytes yet, CAS can't see them
  either — iCloud will materialize a `<name> 2.md` conflict copy on disk.
  This layer then **surfaces** that copy on the *next* write via
  `ConflictCopyError`, rather than leaving it to sit unnoticed.
- **Purely advisory.** The lease only works for writers going through
  `WeaveCore`. A raw text editor, Obsidian itself, or a direct filesystem
  write ignores it completely.
- **TTL takeover is a tradeoff, not a bug.** A writer paused mid-edit
  longer than the TTL (e.g. laptop sleep) can have its lease reclaimed by
  someone else. The CAS backstop still prevents that stale writer's
  eventual write from silently clobbering — it will hit
  `VaultConflictError` instead.
- **The conflict-copy guard is a hard block built on a heuristic, and
  heuristics false-positive.** `find_conflict_copies` matches any sibling
  named `<stem> <digits>.md` — it cannot distinguish an actual unreconciled
  iCloud conflict copy from a file the user genuinely named that way (e.g.
  `weekly-2026 3.md` sitting next to `weekly-2026.md`). Left unmitigated,
  a false positive would **permanently** block every future write to the
  target, because the sibling never goes away on its own. That is why
  `WEAVE_ALLOW_CONFLICT_COPIES` exists (see below): a hard block with no
  escape hatch is worse than an occasionally-wrong guard, so the tradeoff
  is deliberately resolved in favor of always having an out.

**Net effect:** LD#17 goes from prose to code-enforced discipline for the
cases that actually occur day to day, and every write becomes
attributable. That is a large, honest improvement over today's baseline —
not a claim of distributed safety this layer cannot deliver.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `WEAVE_LEASE` | on | Set to `0`/`false`/`no`/`off` to disable L5 entirely. When off, `core._lease()` is a no-op context manager: no sidecar is read or written, no conflict-copy pre-check runs, and neither `LeaseHeldError` nor `ConflictCopyError` can be raised. Behaviour is byte-identical to the L0-only path. |
| `WEAVE_LEASE_TTL_S` | `90` | Seconds after which a lease with no heartbeat refresh is considered stale and eligible for takeover. |
| `WEAVE_OWNER` | unset | Human-readable owner name stamped on the lease (e.g. `SC-Air`). Falls back to `<hostname>/<pid>` if unset. |
| `WEAVE_ALLOW_CONFLICT_COPIES` | off | Set to `1`/`true`/`yes`/`on` to downgrade the pre-write conflict-copy check to a no-op. Use this as the escape hatch when the `<stem> <digits>.md` heuristic false-positives on a legitimately-named file and is blocking writes that should be allowed. Does not affect the lease acquire/refuse/takeover behaviour — only the conflict-copy pre-check. |

### Conflict-copy hard-block and its override

`ConflictCopyError` is a **hard block**: by default, if any sibling file
matches the `<stem> <digits>.md` pattern, every write to the target is
refused, indefinitely, until the sibling is gone. This is deliberate — an
unreconciled iCloud conflict copy sitting there silently is exactly the
failure mode this layer exists to surface — but it means a false positive
(a real file that happens to match the pattern, e.g. `note 2.md` next to
`note.md`) can brick writes to a path with no automatic recovery, since
the guard itself never decides the sibling is "reconciled."

`WEAVE_ALLOW_CONFLICT_COPIES=1` is the documented way out: it skips the
conflict-copy check entirely (the lease acquire/refuse/takeover logic is
unaffected). Set it as a targeted, temporary override — e.g. for the one
session/process touching a path with a known false-positive sibling —
rather than leaving it globally on, since it also suppresses detection of
genuine unreconciled conflict copies for as long as it's set.

Single-user setups (one person, one machine) can run with `WEAVE_LEASE=0`
and pay zero cost. The moment a second machine or a second concurrent
Claude window joins, flip it on (or leave the default, which is already
on). This mirrors the existing `WEAVE_READONLY` env-gate pattern already
used in `weave/mcp_server.py`.

## MCP contract shape

No new MCP tools. `LeaseHeldError` and `ConflictCopyError` propagate out
of the existing `create` / `str_replace` / `insert` / `delete` tools as
ordinary exceptions — callers see a normal tool error and retry. The
5-verb shape (`view`, `create`, `str_replace`, `insert`, `delete`) is
unchanged.
