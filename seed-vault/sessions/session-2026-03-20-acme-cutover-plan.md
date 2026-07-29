---
date: 2026-03-20
type: session
touches: ["[[entity-ACME-v1.2.8]]", "[[entity-Eddie]]", "[[entity-CFO-office]]"]
---

# ACME v1.2.8 Cutover Plan Drafted

Drafted `docs/V1_2_CUTOVER_PLAN.md`. Primary + read replica via Postgres streaming. Blue/green cutover with 30-min window.

**Eddie's asks:**
- Dry-run on staging mirror first
- Migration script peer-reviewed
- Rollback rehearsal documented
