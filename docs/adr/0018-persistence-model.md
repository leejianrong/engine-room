# ADR-0018: Persistence model — in-memory live state, Postgres records, Redis pub/sub only

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Every subsystem now emits durable state (accounts, bots, API-key hashes, ratings, results, PGNs) plus hot live-game state. Redis has surfaced repeatedly (ADR-0005 live state, ADR-0015 fan-out). We pin the storage split. Answers QUESTIONS J1, J2, J3, J4; addresses I3.

## Decision
- **J1 — Live game state is held in-memory in the game's worker process** (the worker the game is pinned to, ADR-0002). Fast, simple, authoritative during play. `python-chess` board + clocks live in-process.
- **J2 — Redis is the pub/sub bus only at MVP** — it fans a game's events out to spectator SSE subscribers across workers (ADR-0015). It is **not** the live-state store at MVP. (Moving live state into Redis for crash-recovery is a deliberate later step.)
- **Durable records → PostgreSQL** (ADR-0005): Users, Bots, API-key hashes, ratings, and **game results**, written at **game-finalization** (Game → FINISHED). ABORTED games record minimally (or not at all) and do not touch ratings.
- **J3 — PGNs ship at MVP.** Because every result is already persisted for Elo (ADR-0011) and `python-chess` produces PGN for free (ADR-0006), storing the full PGN + termination reason is near-free incremental work.
- **J4 — Game history is queryable via API** for bot profiles ("my bot's games", W/L record). Basic and read-only at MVP.

## Alternatives considered
- **Live state in Redis from day one** — survives worker restarts (I3) but every move round-trips to Redis, adding latency and complexity we don't need at MVP scale. Deferred.
- **Persist every move to Postgres live** — durable but slow and unnecessary; we persist the finished game (PGN) instead.
- **Skip PGNs at MVP** — rejected; they're nearly free given Elo persistence and unlock profiles/stats cheaply.

## Consequences
- Positive: minimal moving parts; low-latency play; PGNs + basic stats + history API essentially fall out of what Elo already requires; Redis has exactly one clear job (fan-out).
- Negative / costs: **a worker crash loses its in-progress games** (I3) — accepted at MVP; those games are lost/aborted, not recoverable. Live state and durable records live in different stores, so finalization must reliably write the result (a crash before the finalize-write loses that game's result too).
- Follow-on questions opened:
  - I3 (accepted, revisitable): worker-crash recovery for live games → later Redis/live-state work.
  - PGN retention period + game-history API shape/pagination (minor, build-time).
