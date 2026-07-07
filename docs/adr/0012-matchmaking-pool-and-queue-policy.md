# ADR-0012: Matchmaking pool & queue policy

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
With Elo pairing chosen (ADR-0011), we fix how pools are scoped and how the queue behaves. Answers QUESTIONS E2, E3, E4, E5. Builds on the MatchmakingTicket / lifecycle model (ADR-0009, ADR-0010).

## Decision

- **E2 — Pools segmented by time control.** Each time control (3+0, 5+0, …) is its own matchmaking pool; a Bot only pairs with another Bot in the *same* time-control pool. The Elo widening-window (ADR-0011) operates **within** a pool.
  - Rating scope at MVP: **a single global Elo per Bot** across all time controls (simplicity). Per-time-control ratings (lichess-style) are a future option — see E8.
- **E3 — Anonymous auto-pairing only.** A Bot queues and the system chooses the opponent by Elo within its pool. **No challenge-by-name / direct-challenge** at MVP. (Direct challenges are a future feature.)
- **E4 — Queue give-up.** A MatchmakingTicket has a **max wait TTL**; if no acceptable opponent is found before it expires, the ticket is **CANCELED** (ADR-0010) and the Bot is notified "no opponent found — requeue." A minimum-pool guard prevents pathological instant-pairing edge cases. (Numeric TTL / min-pool values → E8.)
- **E5 — Anti-rematch cooldown.** After two Bots finish a Game together, they are **not re-paired for a cooldown period** (so the same pair can't play back-to-back repeatedly). If they're the only two in the pool, they wait out the cooldown or the ticket TTL expires. (Cooldown length → E8.)

## Alternatives considered
- **One global pool regardless of time control** — rejected; pairing a 3+0 bot against a 5+0 bot is unfair and incoherent.
- **Allowing direct challenges at MVP** — rejected for scope; auto-pairing is the core loop and simplest to ship. Deferred.
- **No anti-rematch rule** — rejected; small pools would otherwise pair the same two bots endlessly, which is boring for spectators and skews ratings.

## Consequences
- Positive: fair same-clock pairings; a simple, predictable queue; ratings stay meaningful with rematch spam curbed.
- Negative / costs: anti-rematch + min-pool + TTL interact badly in a *tiny* pool (two bots may fail to ever pair during cooldown, or time out). Acceptable at MVP; documented as expected low-volume behavior. A single global rating is a simplification that per-time-control play may later outgrow.
- Follow-on questions opened:
  - E8 (extended): all matchmaking numbers — starting rating window, widen rate, fallback timeout, ticket max-wait TTL, min-pool guard, anti-rematch cooldown length; and whether ratings become per-time-control.
