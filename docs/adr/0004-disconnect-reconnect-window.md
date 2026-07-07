# ADR-0004: Mid-game disconnect — reconnect window with the clock still running

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

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
