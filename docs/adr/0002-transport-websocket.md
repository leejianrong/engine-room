# ADR-0002: WebSocket as the bot ↔ server transport

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Bots must "stream the game state and execute standard chess moves back and forth with low latency," and the spectator dashboard must update "without refreshing the page." Both need server→client push. Answers QUESTIONS B1, B2; informs F1.

## Decision
Bots connect over a **persistent WebSocket**. The server **pushes** turn events to the bot (`your_turn` with the current state); the bot sends moves back over the same socket. The same WebSocket real-time primitive is reused for the spectator fan-out (to be detailed in a spectating ADR), so the system has **one** real-time technology rather than several.

## Alternatives considered
- **SSE (server→bot) + REST (bot→server)** — easier on serverless hosts, but two channels to correlate and higher move latency. Only justified by a hard serverless constraint, which we do not have.
- **REST + polling** — trivial and hostable anywhere, but the poll interval becomes a latency floor and wastes resources at scale; unacceptable for Blitz.
- **gRPC bidirectional streaming** — great latency and a typed contract, but a heavy client dependency that hurts the "AI student writes a Python script in 20 minutes" onboarding story.

## Consequences
- Positive: lowest-latency bidirectional path; natural fit for turn-based push; one primitive reused for spectators; broad client-language support incl. browsers.
- Negative / costs: persistent connections complicate horizontal scaling and rule out naive serverless deployment (a game is pinned to the process holding its sockets — see QUESTIONS K2/K3, I3). Requires an explicit connection lifecycle (handshake, auth, heartbeats).
- Follow-on questions opened: message/wire format (B3–B5), handshake & version negotiation (B6), heartbeat/ping cadence, how a game's two sockets are colocated on one process (K2).
