---
type: session
date: '2026-04-15'
---

# Orchard barcode bug

Reproduced the scanner fault: EAN-8 labels lose their LEADING ZEROS on
scan, so crate lookups miss. Root cause: integer cast in the intake parser.
Fix scheduled next sprint. [[entity-Project-Orchard]]
