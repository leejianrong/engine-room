# Engine Room — server

FastAPI + Postgres backend (V1–V7 complete). See [../CLAUDE.md](../CLAUDE.md) for the build-status
map and [../docs/shaping/](../docs/shaping/) for the per-slice plans.

## Develop

```bash
# 1. Postgres (from repo root)
docker compose up -d db

# 2. Install deps (creates .venv)
cd server
uv sync

# 3. Apply migrations
uv run alembic upgrade head

# 4. Run the API (port 8001; 8000 is used by another app)
uv run uvicorn engine_room.app:app --reload --port 8001
# -> http://127.0.0.1:8001/health

# Tests — layered by cost (see ../docs/DEVELOPER-WORKFLOWS.md)
uv run pytest tests/unit -q          # fast, no infra (in-process ASGI / live-uvicorn-no-DB)
uv run pytest tests/integration -q   # needs Docker: ephemeral Postgres via testcontainers
uv run pytest                        # everything
```

Shared test helpers (the fake protocol client — the primary WS test seam) live in `tests/support/`.
Config via `ER_`-prefixed env vars (see `.env.example`).
