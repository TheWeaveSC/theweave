---
date: 2025-11-01
type: session
touches: ["[[entity-ACME]]", "[[entity-Marcus]]", "[[entity-CFO-office]]"]
---

# ACME Kickoff

Marcus agreed to lead initial deployment. CFO signed off on the single-instance design — replication deferred to "future phase". Target: production by mid-November.

**Decisions:**
- Postgres 15, single instance
- Deploy on Mac mini (Marcus's machine)
- No replication in v1.0.x

**Open questions parked for later:**
- Replication: when?
- Backup DBA: who?
