# Architecture

Engine Room is a single-process, server-authoritative real-time system with two
deployable services and a Postgres store.

## High-level shape

```
        ┌─────────────┐   WebSocket (Bearer crbk_ key)   ┌──────────────────────┐
Bots ──▶│  WS handshake│ ───────────────────────────────▶│  FastAPI backend     │
        └─────────────┘                                  │  (:8001)             │
                                                          │                      │
Humans ─── GitHub OAuth / JWT ── REST /api/* ────────────▶│  • matchmaking loop  │
                                                          │  • game engine       │
        ┌─────────────┐   Server-Sent Events (live)       │  • python-chess rules│
Browser◀│ SvelteKit SPA│◀──────────────────────────────── │  • server clock      │
        │  (:5174)     │                                  └──────────┬───────────┘
        └─────────────┘                                             │
                                                          ┌──────────▼───────────┐
                                                          │  PostgreSQL (:5433)  │
                                                          └──────────────────────┘
```

## Backend (`server/engine_room/`)

- **FastAPI + SQLAlchemy 2.0 async + Alembic + Postgres.** Managed with `uv`.
- **Matchmaking** — an Elo widening-window matcher (`MatchmakingQueue`) pairs seekers
  across 3+0 and 5+0 pools with same-owner exclusion and soft anti-rematch. Pairing
  runs on a background matcher loop; a house "greeter" bot serves lone seekers.
- **Game engine** — server-authoritative: legality is enforced with `python-chess`, the
  clock is kept server-side, and games are finalized to Postgres.
- **Auth** — GitHub OAuth for humans (stateless JWT), per-bot HMAC-hashed API keys for
  the bot WebSocket handshake.

## Frontend (`frontend/`)

- **TypeScript + SvelteKit + Vite**, shipped as a static SPA. It watches a single game by
  `?game=<id>` and renders live moves streamed over SSE.

## Testing layers

| Layer | Infra | When |
|-------|-------|------|
| `tests/unit/` | none (in-process ASGI or uvicorn thread, no DB) | pre-push hook + CI |
| `tests/integration/` | ephemeral Postgres via testcontainers (Docker) | CI + local-with-Docker |
| `tests/support/` | shared fake protocol WS client (primary test seam) | — |

## Build slices

The product is sliced **V1–V7** (walking-skeleton-first). V1–V3 are done (skeleton,
identity, matchmaking); V4 adds reconnect/idempotency/heartbeat; later slices cover
ratings, dashboard/replay, and the packaged client SDK. See the `shaping/` documents in
the repository's `docs/` tree for the full plan.
