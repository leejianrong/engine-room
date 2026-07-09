# ADR-0004: Mid-game disconnect — reconnect window with the clock still running

- **Status:** **superseded by ADR-0025 #3** (the reconnect *window* is removed — the
  clock is the sole arbiter). The rest stands: resume-the-same-game, clock-runs-while-away,
  and `ply`-idempotency. **Realized in V4** (slice A4 / `docs/shaping/V4-plan.md`).
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

> **Superseded note (ADR-0025 #3, realized in V4):** there is **no separate reconnect
> window** that forfeits independently. A disconnected bot loses only by **flagging on its
> own clock** (on its turn) or by an illegal move; it may reconnect anytime the game is
> live and resume from `welcome.active_game` (PROTOCOL §8). A heartbeat/liveness timeout is
> used **only** to detect **mutual abandonment** (both seats gone → ABORTED), never to
> forfeit a single bot. Everything below about *window expiry = forfeit* is therefore
> obsolete; the "resume the same game, clock keeps running, idempotent move-resend" parts
> are what V4 built.

## Context
Bots run on users' own home machines and cloud instances (REQS), so connections will blip. We must decide what happens when a bot's WebSocket (ADR-0002) drops mid-game. Answers QUESTIONS I1, I2; informs H3.

## Decision
On disconnect, the bot may **reconnect and resume the same game within a reconnect window**. During the gap, the bot's **game clock keeps running**. On reconnect, the server replays the current authoritative state so the bot can continue. If the window expires **or** the bot flags while disconnected, it is a **loss** (forfeit).

## Alternatives considered
- **Instant loss on any drop** — trivially simple but hostile to hobbyists on flaky connections; would generate "bug reports" that are really just someone's wifi.
- **Pause clock + grace, then abort with no result** — kind to hobbyists, but lets a bot in a losing position dodge the loss by pulling its cord. Exploitable.

## Consequences
- Positive: forgiving of transient blips (resume where you left off) while making it impossible to escape a lost position or a flag by disconnecting — the running clock enforces honesty. Good fit for the hobbyist audience without opening an exploit.
- Negative / costs: requires session-vs-connection separation (a Bot's game identity must outlive a single socket — see QUESTIONS A4), state replay on reconnect, and idempotency so a move sent right before a drop isn't lost or double-applied (I4).
- Follow-on questions opened: How long is the reconnect window (fixed seconds vs a fraction of remaining clock)? Does the opponent keep thinking during the gap (yes — it may be their turn)? Reconnect authentication — same token, resume by game id? (→ new I5–I6 below.)
