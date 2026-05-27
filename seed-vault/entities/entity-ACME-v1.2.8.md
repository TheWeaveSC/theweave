---
name: entity-ACME-v1.2.8
type: project
version: v1.2.8
valid_from: 2026-03-15
valid_until: null
supersedes: "[[entity-ACME]]"
status: current
---

# ACME Project (v1.2.8) — CURRENT

Replication-enabled rebuild of the ACME ERP. Primary + read replica via Postgres streaming. Cutover plan drafted; dry-run pending.

**Health:** 🟡 awaiting cutover. Marcus still on v1.0.7 in production.

## Links
- Cutover plan: [[session-2026-03-20-acme-cutover-plan]]
- Migration script review: [[session-2026-04-02-acme-migration-review]]
- Dry-run blockers: [[session-2026-05-10-acme-dryrun-blockers]]

## Related
- [[entity-Marcus]] — needs migration window
- [[entity-CFO-office]] — primary stakeholder
- [[entity-DBA-coverage]] — depends on cutover completing

## Next action
Dry-run pending per `docs/V1_2_CUTOVER_PLAN.md`. Marcus's slot opens 2026-06-01.
