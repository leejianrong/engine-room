# Optional / advanced (ADR-0024): the hero path is `uv run python random_bot.py`
# on your machine — no container. This Dockerfile is for the containerized path.
#
# CAVEAT (pre-PyPI, V7 O-2): while `chessroom` is path-installed from the monorepo
# (../chessroom), build with the repo's `sdk/` as the context so the sibling
# package is present:  `docker build -f quickstart/Dockerfile -t my-bot sdk/`
# Once chessroom is on PyPI, drop that and build from `quickstart/` directly.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY chessroom /chessroom
COPY quickstart /app

RUN uv sync

# Pass CHESSROOM_KEY (and CHESSROOM_URL) at runtime:
#   docker run -e CHESSROOM_KEY=crbk_... my-bot
CMD ["uv", "run", "python", "random_bot.py"]
