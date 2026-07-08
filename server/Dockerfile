# Backend image: FastAPI + uv. Runs migrations then serves on :8001.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install runtime deps first (cached unless deps change). --no-dev skips
# ruff/pytest/testcontainers/etc.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the app itself.
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8001
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn engine_room.app:app --host 0.0.0.0 --port 8001"]
