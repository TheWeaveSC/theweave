---
date: 2026-04-02
type: session
touches: ["[[entity-ACME-v1.2.8]]", "[[entity-Marcus]]"]
---

# ACME Migration Script Reviewed

Marcus + Sonnet walked through `migrations/v1_0_7_to_v1_2_8.sql`. Two issues fixed:

1. Missing `IF NOT EXISTS` guard on the new `audit_log` table — would have failed on re-run.
2. Foreign key on `journal_entry.created_by` pointed at the old `user_id` column; updated to new UUID.

Marcus approved the script. Dry-run scheduled for May.
