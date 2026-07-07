# ADR-0025: A2 consistency pass — fixes & clarifications

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude
- **Amends:** ADR-0004, ADR-0016, ADR-0018, ADR-0019, ADR-0022
- **Resolves:** QUESTIONS C7, I5

## Context
The A2 inconsistency review surfaced two contradictions, three ambiguities, and two gaps across ADR-0001..0024. This ADR records their resolution in one place.

## Decisions

1. **House-bot exemption from same-owner exclusion (amends ADR-0016 H5, ADR-0022).** The same-owner exclusion applies only to **real user accounts**; **house bots are exempt** and may be paired against each other. Rationale: the rule exists to stop real-user rating-farming, which house bots do not do — and house-vs-house games are required to keep the lobby lively (ADR-0022). *(Fixes: same-owner rule otherwise forbade the house-vs-house games ADR-0022 depends on.)*

2. **No Redis in the MVP (amends ADR-0018; clarifies ADR-0020/0023).** The single-process MVP uses **in-memory matchmaking queues** and **in-process pub/sub** — Redis provides nothing when there is only one worker. Both sit behind **narrow interfaces** (a `MatchmakingQueue` and a `PubSub`/event-bus abstraction) so the scale-out swap to Redis (ADR-0020) is an implementation change, not a rewrite. Redis becomes a dependency **only at multi-worker scale-out.** *(Fixes: ADR-0018 called Redis an MVP component for cross-worker fan-out, but MVP is single-process.)*

3. **Clock is the sole arbiter of a bot's time (amends ADR-0004; resolves I5).** There is **no separate reconnect-window** that forfeits independently. A disconnected bot loses only by **flagging on its own clock** (on its turn) or by illegal move; it may reconnect anytime the game is live (auto-flag detection per ADR-0003). A disconnect during the *opponent's* turn is harmless (its clock isn't running). A **heartbeat/liveness timeout** is used *only* to detect **mutual abandonment** (both sides gone) → ABORTED (I7), never to forfeit a single bot. Matches lichess/chess.com, where the clock governs and the "opponent left" claim is a human-presence shortcut irrelevant to bots.

4. **Queue over the WebSocket (amends ADR-0019; resolves C7).** A bot queues by sending a **`seek` message** (including desired time control) over its already-open authenticated WebSocket (ADR-0014); matching and all game events flow over the same socket. This makes ADR-0016's "both bots already connected at PAIRED" true and matches the persistent-connection model of lichess/chess.com. Because the bot picks its time control in the seek, **time control is per-seek selectable (resolves C7).** Rate limits (ADR-0019) are reframed: **per-session `seek`-message rate + per-user/IP connection rate**. Management (bot CRUD/keys) stays REST; spectating stays SSE.

5. **Atomic finalization (amends ADR-0018).** Result + Elo update + PGN are written in a **single Postgres transaction** at game-end, so a crash cannot desync ratings from saved games.

6. **Increment carried-but-dormant.** MVP time controls (3+0, 5+0) have zero increment; the `{base, increment}` model is retained but its increment path is **untested at MVP**. Add an increment control (e.g. 3+2) if/when we want to exercise it. (No new control added now.)

7. **Spectator connection cap (amends ADR-0019).** Anonymous SSE spectating gets a **per-IP connection cap** to blunt the trivial open-thousands-of-streams DoS vector.

## Consequences
- Positive: removes Redis (a moving part) from the MVP; simpler, real-platform-aligned disconnect logic; one persistent channel per bot for connect→seek→play; crash-safe finalization; closed DoS gap. Resolves C7 and I5.
- Negative / costs: the `MatchmakingQueue`/`PubSub` interfaces must be designed for the eventual Redis swap (small upfront discipline); heartbeat timeout is a new (non-blocking) tuning value.
- Follow-on questions opened: heartbeat interval/timeout value (tuning); confirm `seek` message schema in the protocol spec (ADR-0021).
