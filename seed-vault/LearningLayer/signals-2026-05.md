---
month: 2026-05
type: learning-signals
---

# LearningLayer Signals — May 2026

Domain-agnostic observations. Signals only, never work content. (LD #13)

## Communication patterns
- User prefers terse phrasing but expects depth-matched replies (length follows verb)
- Direct corrections are common and welcome
- "Parking Lot" = defer, finish current work first

## Working preferences
- Reviews architectural decisions in writing before commit
- Wants honest "what works / what's stubbed" rather than optimistic claims
- Sleep-time builds: tolerate aggressive scope IF clearly bounded + sandboxed

## Failure modes observed
- Lossy parser in session-end pipeline (parser bugs around `## What We Did` heading)
- Static boot file → manual re-orientation cost on every new session
