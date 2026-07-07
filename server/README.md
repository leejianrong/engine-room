# Engine Room — server

FastAPI + Postgres backend. See [../docs/shaping/V1-plan.md](../docs/shaping/V1-plan.md) for the current slice.

## Develop

```bash
# 1. Postgres (from repo root)
docker compose up -d db

# 2. Install deps (creates .venv)
cd server
uv sync

# 3. Apply migrations
uv run alembic upgrade head

# 4. Run the API
uv run uvicorn engine_room.app:app --reload
# -> http://127.0.0.1:8000/health

# Tests (fake-protocol-client WS seam)
uv run pytest
```

Config via `ER_`-prefixed env vars (see `.env.example`).
