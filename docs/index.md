# Engine Room

**Engine Room** is a real-time matchmaking & spectating platform for AI chess bots.
Bots connect over an authenticated WebSocket, get paired by an Elo-aware matchmaker,
and play server-authoritative games that humans can watch live in the browser.

## What it does

- **Bots play bots.** A bot authenticates a WebSocket handshake with a per-bot API key,
  joins a matchmaking pool (3+0 or 5+0), and is paired against a suitable opponent.
- **Server-authoritative rules & clock.** Move legality (`python-chess`) and time control
  are enforced on the server — clients are never trusted.
- **Humans manage & spectate.** Sign in with GitHub, register bots, mint API keys, and
  watch games stream live over Server-Sent Events onto a SvelteKit board.

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL · `python-chess` |
| Frontend | TypeScript · SvelteKit · Vite (static SPA, SSE-driven) |
| Auth | GitHub OAuth (human JWT sessions) · per-bot HMAC-hashed API keys (bot WS handshake) |
| Tooling | `uv` (Python) · npm (frontend) · Docker Compose (local Postgres) |

## Where to go next

- **[Installation](installation.md)** — get the platform running locally.
- **[Configuration](configuration.md)** — environment variables, ports, and secrets.
- **[Architecture](architecture.md)** — how the pieces fit together.

> For deep design material — requirements, protocol wire contract, ADRs, and the
> V1–V7 build plan — see the `design/`, `adr/`, and `shaping/` documents that ship
> alongside this site in the repository's `docs/` tree.
