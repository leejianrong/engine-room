# ADR-0015: Spectator delivery over SSE — anonymous, no broadcast delay, catch-up on join

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Human spectators must watch live games in the browser without refreshing (REQS). This is the second real-time surface, distinct from the bot WebSocket (ADR-0002). Answers QUESTIONS F1, F2, F5, F6; opens F3, F4.

## Decision
- **F1 — Transport: Server-Sent Events (SSE).** Spectating is read-only, so a one-way stream fits: browser `EventSource` gives auto-reconnect for free and keeps a clean **trust boundary** — bots use authenticated bidirectional WebSockets (ADR-0002/0014); spectators use anonymous read-only SSE. A spectator subscribes to a per-game stream (`GET /games/{id}/stream`).
- **F2 — No broadcast delay at MVP.** In bot-vs-bot play the players *are* engines that already receive the full authoritative position over their own WebSocket, so a spectator view of one's own game leaks nothing. The anti-relay purpose of broadcast delay (a human-chess concern) does not apply. Incidental SSE latency exists but is **not** relied upon as a safeguard.
- **F5 — Catch-up on join + replay.** On connect, a spectator receives the **current snapshot** (FEN, both clocks, full move list, players + ratings, game state); the SSE stream then delivers each subsequent move, clock update, and the terminal result. The move history/PGN is available so a client can **replay from move 1** locally.
- **F6 — Anonymous spectating (no login).** Maximizes the "casually log on and watch" funnel for brand-new visitors and is the simpler MVP path. (Login remains available for owners managing bots, per ADR-0013.)

## Alternatives considered
- **WebSocket for spectators** — rejected; bidirectionality is unneeded, SSE auto-reconnect is simpler, and mixing anonymous spectators onto the authenticated WS surface muddies the trust boundary.
- **Polling** — rejected; latency + waste, poor "live" feel.
- **Broadcast delay/buffer** — rejected; no anti-cheat value in bot-vs-bot (see F2).
- **Account-gated spectating** — rejected for MVP; hurts the discovery funnel with no MVP benefit.

## Consequences
- Positive: dead-simple read-only fan-out with free browser reconnect; clean separation of bot vs spectator concerns and trust levels; instant catch-up for late joiners.
- Negative / costs: **cross-worker fan-out** — a game is pinned to one worker (ADR-0002) but SSE spectators can connect to any worker, so multi-worker deployment needs an **internal pub/sub (e.g. Redis)** to broadcast a game's events to all workers' subscribers (confirms the ADR-0005 "Redis later" note; ties to K2). SSE has a per-browser connection cap (~6 over HTTP/1.1) — a non-issue for one game view, relevant if a page opens many streams; HTTP/2 mitigates.
- Follow-on questions opened:
  - F3: what the **active-games list** shows (players, ratings, time control, move count, live?) and how it updates (poll vs its own lightweight SSE lobby stream).
  - F4 / K2: concurrent-spectator fan-out scale and the Redis pub/sub design for multi-worker broadcast.

## Addendum (2026-07-09, V6): F1/F3/F5 realized
- **F5 catch-up + replay — built.** A spectator SSE connection now leads with a `snapshot` event (`Game.spectator_snapshot()` from the in-memory `LiveState`: current fen/ply/clocks, both players+ratings, state, and the full move-list-so-far) *before* the live tail. The endpoint subscribes to the game channel **before** reading the snapshot, so no tail event is lost across the join; a move landing in that window arrives in both the snapshot and the tail and the client dedups by `ply` (mirrors V4 §9 idempotency). Replay-from-move-1 runs over one uniform `[{ply,san,uci,fen}]` list — from `LiveState.moves` for a live game, or reconstructed from the stored **PGN** (`GET /api/games/{id}`) for a finished one, so the client needs no chess engine (the server emits per-ply FEN).
- **F3 active-games list — built as a poll.** `GET /api/games` returns active games (from the in-memory registry, ADR-0020) merged with the most-recently-finished (from Postgres); the dashboard polls it every 3s. A dedicated lobby **SSE** stream stays the scale path (deferred). The spectator `game_over` SSE event also now carries the per-side rating change (V5 Q6).
- **F1/F6 unchanged** — anonymous read-only SSE per game. Cross-worker fan-out / Redis (F4/K2) remains the scale-out path (still single-process, in-proc pubsub at MVP). See docs/shaping/V6-plan.md.
