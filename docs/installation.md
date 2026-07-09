# Installation

Engine Room is a two-service application: a **FastAPI backend** and a **SvelteKit
frontend**, backed by **PostgreSQL**. Local development uses [`uv`](https://docs.astral.sh/uv/)
for Python and Docker Compose for the database.

## Prerequisites

- Python 3.10+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js (with `npm`) for the frontend
- Docker (for local Postgres via Docker Compose)

## Quick start

The fastest path is the Makefile:

```bash
make demo   # whole platform + a looping demo bot in Docker (watch a live game)
make dev    # db + backend + frontend with hot reload
make bot    # (another terminal) start a game against the house bot
```

## Manual setup

```bash
# 1. Start Postgres (host port 5433)
docker compose up -d db

# 2. Backend — install deps, run migrations, serve on :8001
cd server
uv sync
uv run alembic upgrade head
uv run uvicorn engine_room.app:app --reload --port 8001   # http://localhost:8001/health

# 3. Frontend — install deps, dev server on :5174
cd frontend
npm install
npm run dev
```

## Ports

| Service   | Port |
|-----------|------|
| Backend   | 8001 |
| Frontend  | 5174 |
| Postgres  | 5433 |

All ports are moved off their defaults to avoid collisions. The frontend talks to the
backend **cross-origin via CORS** (see `cors_allow_origins` in `config.py`), not a proxy.

## Verifying the install

```bash
cd server   && uv run ruff check . && uv run pytest tests/unit -q   # fast (no Docker)
cd server   && uv run pytest tests/integration -q                  # needs Docker
cd frontend && npm run check                                       # svelte-check
```
