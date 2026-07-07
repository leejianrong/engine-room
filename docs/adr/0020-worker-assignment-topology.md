# ADR-0020: Worker assignment & connection topology

- **Status:** accepted (recommendation — flip to redirect model on preference)
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
A Game's authoritative state is in-memory in one worker (ADR-0002, ADR-0018), but two bots' WebSockets can land on different workers behind a load balancer. We must define how a game maps to a worker and how sockets reach it. Answers QUESTIONS K2; ties F4, I3.

## Decision

- **MVP: a single game-worker process.** Pinning is trivially satisfied — all bot sockets and all games are in one process. No cross-worker routing for bot moves is needed yet. Postgres and Redis are external. Scale vertically first.

- **Scale-out (recommended path): Redis-bridged edge/home-worker model** — do **not** migrate sockets; decouple socket location from game location:
  - **Matchmaking queues live in Redis** (per-time-control, rating-ordered) so pairing is **global** across workers.
  - The matchmaker assigns each new game to a **least-loaded home worker** (per-worker game counts in Redis) and records `game_id → home_worker` in a Redis registry.
  - The **home worker** owns the authoritative in-memory board + clock (preserves ADR-0018).
  - Bots keep sockets on their **edge worker**. Move flow: edge worker → `game:{id}:moves` (Redis) → home worker validates/applies → `game:{id}:events` (Redis) → consumed by both bots' edge workers (push to sockets) **and** spectator workers (SSE fan-out).
  - **The bot event bus and the spectator fan-out bus are the same Redis channel** (ADR-0015) — no new infrastructure.

- **Nuance vs ADR-0002:** *game state* stays pinned to one worker; the requirement that *sockets be colocated with it* is relaxed — Redis bridges them.

## Alternatives considered
- **Redirect-to-home-worker (force colocation)** — bots reconnect to the specific home worker so everything runs in-process. Rejected as default: needs per-worker addressability (no simple LB), adds a reconnect round-trip at game start, and doesn't reuse the spectator bus. Still a valid flip if in-process simplicity is preferred over the LB simplicity.
- **Per-worker local queues** — rejected; would only pair bots that happened to hit the same worker.

## Consequences
- Positive: simplest possible MVP (one process); a clean scale path that **reuses the Redis bus spectating already requires**; reconnect-friendly (a reconnecting bot lands on any edge worker and re-subscribes); simple load balancing (sockets land anywhere). Sub-ms local-Redis hop is negligible at Blitz (ADR-0003).
- Negative / costs: at scale, more moving parts (game→worker registry, worker liveness); a **home-worker crash loses its in-progress games** (I3, already an accepted MVP risk); every move crosses Redis.
- Follow-on questions opened: worker liveness/failover + game→worker rebalancing; F4 concurrent-spectator fan-out limits; whether the matchmaker is a dedicated coordinator or a leader-elected worker.
