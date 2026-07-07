# ADR-0003: Server-authoritative clock; the bot eats its own network latency

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
The server must strictly enforce the game clock and timeout = loss (REQS). We must decide how network latency counts against a bot's clock. Depends on ADR-0001 (Blitz floor). Answers QUESTIONS C1, C2, C6.

## Decision
The **server is the single source of truth for the clock.** A bot's clock **starts** the moment the server sends the `your_turn` event and **stops** the moment the server receives the bot's move. Elapsed time therefore **includes** the bot's network round-trip — the bot eats its own latency. Flag (timeout) is **auto-detected server-side**, not claimed by the opponent. No RTT compensation at MVP.

## Alternatives considered
- **RTT compensation per move** — fairer for far-away bots (`charged = elapsed - estimated_RTT`), but adds moving parts and a spoofing/latency-gaming surface. Not worth it at Blitz budgets.
- **Flat per-move grace allowance** — coarse jitter absorber, but arbitrary and gameable.

## Consequences
- Positive: dead-simple, fully authoritative, zero clock-spoofing surface. At Blitz move budgets (multi-second) a few hundred ms of RTT is negligible, so this is fair enough. Server-side flag detection means results are deterministic and instant.
- Negative / costs: penalizes geographically distant bots; becomes unfair if/when we introduce Bullet. This ADR must be revisited (likely superseded) as part of any Bullet work — RTT compensation and/or regional servers would be prerequisites.
- Follow-on questions opened: exact clock start point (does it count from server-send or from socket-flush?), monotonic clock source on the server, how increment is credited, behavior during a reconnect gap (→ ADR-0004).
