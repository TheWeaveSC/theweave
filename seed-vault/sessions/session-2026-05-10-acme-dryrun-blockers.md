---
date: 2026-05-10
type: session
touches: ["[[entity-ACME-v1.2.8]]", "[[entity-Marcus]]"]
---

# ACME Dry-Run Blockers Surfaced

Pre-flight check found replication lag spike (>30s) on the staging mirror under load. Marcus flagged this as a hard blocker for the production cutover — "I'm not migrating production with a known lag issue."

**Root cause:** WAL sender buffer too small for the journal-entry write rate.

**Fix:** tune `wal_sender_timeout` + `max_wal_senders`. Re-test mid-May.

**Marcus's window:** opens 2026-06-01. Dry-run must be green by then or we slip.
