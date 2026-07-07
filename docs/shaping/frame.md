---
shaping: true
---

# Engine Room MVP — Frame

## Source

The design has already been fully grilled and documented:
- [REQS.md](../design/REQS.md) — original idea, problem, users, outcomes, scope.
- [CONTEXT.md](../design/CONTEXT.md) — glossary, domain model + invariants, 26-row decisions log, MVP definition.
- [docs/adr/0001–0025](../adr/) — architecture decision records (the "why" behind every choice).
- [PROTOCOL.md](../design/PROTOCOL.md) — the bot↔server WebSocket wire contract, v1.0.
- [docs/PRD.md](../design/PRD.md) — the build brief (problem, solution, 76 user stories, implementation + testing decisions, scope).

Demoable slice (ADR-0023), the north star for this shaping:

> A developer signs in with GitHub, creates a bot (key shown once), clones the quickstart, runs it, and within minutes watches their bot get matched against a house bot and play a full **3+0 Blitz** game to a real result — live on a public spectator dashboard, clock enforced server-side, PGN saved to the bot's profile.

## Problem

The product problem is settled in REQS/PRD (no low-friction home for automated chess players; bot-vs-bot matchmaking + live spectating). **This shaping does not re-open it.**

The problem *this shaping* solves is a build-planning one: the architecture is fully decided across 25 ADRs, but there is **no implementation plan** — no agreed way to break the MVP into increments we can build, demo, and de-risk in order. Built in the wrong order, the riskiest parts (real-time spine: WebSocket + server clock + rules + finalization) surface late, and there is nothing watchable until the very end.

## Outcome

A slicing plan where:
- We reach the **demoable slice** (zero → live watchable game) by a known sequence of increments.
- **Every increment ends in something observable** (a demo), not a horizontal layer.
- The **riskiest mechanics are proven early**, not deferred to integration.
- The **hero path** (SDK / quickstart / RandomBot; ADR-0023) is prioritized over secondary polish (UCI bridge, lobby SSE, dashboard chrome).
- We stay inside the MVP scope boundary and build behind the seam interfaces (`MatchmakingQueue`, `PubSub`) so scale-out isn't precluded.
