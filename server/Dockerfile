# Backend image: FastAPI + uv. Runs migrations then serves on :8001.
#
# Single origin (V8, KAN-68): the SvelteKit SPA is built in a Node stage and baked
# into this image, then served same-origin by uvicorn via Starlette StaticFiles (no
# nginx, no separate frontend app). The frontend calls the API relative (same host),
# so no VITE_API_BASE is baked in.

# --- Frontend build stage (mirrors frontend/Dockerfile) ---
FROM node:22-slim AS frontend
WORKDIR /web
# The frontend lives one level up from this Dockerfile's build context (server/),
# so builds must use the repo root as context: `docker build -f server/Dockerfile .`
# Fly does this automatically (fly.toml `dockerfile`); see docs/DEPLOY.md.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin: VITE_API_BASE defaults to '' (relative). No build arg needed.
RUN npm run build

# --- Backend runtime ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install runtime deps first (cached unless deps change). --no-dev skips
# ruff/pytest/testcontainers/etc.
COPY server/pyproject.toml server/uv.lock server/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the app itself.
COPY server/ .
RUN uv sync --frozen --no-dev

# Bake the built SPA in and point the app at it (served same-origin, no nginx).
COPY --from=frontend /web/build ./frontend_build
ENV ER_STATIC_DIR=/app/frontend_build

EXPOSE 8001
# --proxy-headers + --forwarded-allow-ips=* are LOAD-BEARING behind Fly's TLS proxy:
# without them uvicorn sees http on the internal port and FastAPI-Users builds an
# http:// OAuth redirect_uri that GitHub rejects. Safe: only Fly's proxy reaches 8001.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn engine_room.app:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips=*"]
