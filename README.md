# Engine Room

A real-time matchmaking and spectating platform for **AI chess bots** — think "Chess.com for bots." Humans register bots; bots connect outward over a WebSocket to be matched by Elo and play **bot-vs-bot** games that anyone can watch live in the browser.

> **Status:** MVP complete. All seven slices are built and merged — **V1** walking skeleton, **V2** GitHub identity + bot keys, **V3** Elo matchmaking, **V4** resilience (reconnect/idempotency/heartbeat), **V5** outcomes + real ratings, **V6** spectator UX (lobby/catch-up/replay/ambient bots), and **V7** the packaged `engineroom` SDK + `uv` quickstart + UCI bridge. Deployed on Fly.io at **https://engine-room.fly.dev**. See the [build plan](docs/shaping/slices.md) and per-slice plans in [docs/shaping/](docs/shaping/).

## What it does (MVP / demoable slice)

A developer signs in with GitHub, creates a bot (API key shown once), clones the quickstart, runs it, and within minutes watches their bot get matched against a house bot and play a full **3+0 Blitz** game to a real result — live on a public spectator dashboard, clock enforced server-side, PGN saved to the bot's profile.

- **Bots** ↔ server: authenticated bidirectional **WebSocket** (server pushes turns; bot replies with UCI moves). Server is the sole authority for the clock and move legality (`python-chess`).
- **Spectators**: anonymous, read-only **SSE** stream — live board, catch-up on join, replay.
- **Matchmaking**: Elo pools per time control, house bots always present so newcomers get an instant game.

Full scope, non-goals, and the 76 user stories are in the [PRD](docs/design/PRD.md).

## Repository layout

```
engine-room/
  server/      FastAPI + Postgres backend (uv)          -> server/README.md
  frontend/    SvelteKit spectator UI (Vite, static SPA) -> frontend/README.md
  sdk/         engineroom SDK + uv quickstart template     -> sdk/engineroom/README.md, sdk/quickstart/README.md
  docs/        design, decisions, and the build plan     -> docs/README.md
  docker-compose.yml   local Postgres (host port 5433)
```

## Documentation

Start at the **[docs index](docs/README.md)**. The key documents:

| Doc | What it is |
|-----|------------|
| [docs/design/REQS.md](docs/design/REQS.md) | Original idea, problem, users, scope. |
| [docs/design/CONTEXT.md](docs/design/CONTEXT.md) | Glossary, domain model + invariants, decisions log, MVP definition — the hub tying the ADRs together. |
| [docs/design/PRD.md](docs/design/PRD.md) | Product requirements: problem, solution, user stories, implementation + testing decisions, out-of-scope. |
| [docs/design/PROTOCOL.md](docs/design/PROTOCOL.md) | The bot↔server WebSocket wire contract (v1.0). |
| [docs/design/QUESTIONS.md](docs/design/QUESTIONS.md) | The grilling backlog: resolved decisions + open build-time items. |
| [docs/adr/](docs/adr/) | Architecture decision records 0001–0025 — the "why" behind every choice. |
| [docs/shaping/](docs/shaping/) | The build plan: [frame](docs/shaping/frame.md) → [shaping](docs/shaping/shaping.md) (Shape A) → [slices](docs/shaping/slices.md) (V1–V7) → [V1-plan](docs/shaping/V1-plan.md). |

**New here?** Read `REQS → CONTEXT → PRD → PROTOCOL`, dipping into `adr/` for rationale. For the build plan, read `shaping/frame → shaping → slices → V1-plan`.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy 2.0 (async) + Alembic, Postgres, `python-chess`; packaged with `uv`.
- **Frontend:** TypeScript, SvelteKit + Vite (static SPA, SSE-driven).
- **Bot SDK:** `engineroom` Python package at [`sdk/engineroom`](sdk/engineroom/) — a decoupled `uv` project that depends only on the versioned protocol spec, never on server code (ADR-0021, enforced by an import-boundary test). It currently lives in this monorepo; the standalone-repo split + PyPI publish are deferred (V7 O-2).

## Try it out — watch a live match (one command)

```bash
make demo        # builds & runs db + backend + frontend + a looping demo bot (all in Docker)
```

Open **http://localhost:5174** — the **dashboard** shows a live lobby (ambient house-vs-house
games keep it populated even with no real bots). Click any game to watch it from the current
position and scrub the replay from move 1. `make down` stops everything (`make down-clean` also
wipes the Postgres volume for a clean slate).

## Write and run your own bot (the hero path)

Bots are external clients that connect *to* the platform, using the **`engineroom` SDK**: you
subclass `Bot`, implement `choose_move(board)` (a `python-chess` board), and call `run()` — the SDK
handles the WebSocket, matchmaking, clocks, reconnects, and the wire protocol. The
[`sdk/quickstart`](sdk/quickstart/) template is the newcomer path:

```bash
make dev                              # terminal 1: db + backend + frontend (hot reload)

make sdk-bot                          # terminal 2: mints a key + runs the SDK's quickstart
                                      #   RandomBot vs the house — appears live on the dashboard
```

To feel the real newcomer flow (what the quickstart README walks through):

```bash
cd sdk/quickstart
cp .env.example .env                  # paste a key from `make mint`; uncomment ENGINEROOM_URL for local
uv sync
uv run python random_bot.py
```

Point an existing UCI engine at the platform instead:

```bash
cd sdk/engineroom
ENGINEROOM_KEY=crbk_... uv run engineroom-uci --engine /path/to/stockfish
```

There's also `make bot` — the older dev demo client (`engine_room.devtools.demo_bot`, minimax,
raw websockets) that predates the SDK; the SDK is the supported way to write a bot.

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js, Docker. Run `make` (or `make help`)
to see every target.

```bash
make install     # once per clone: uv sync + npm install
make dev         # db + backend + frontend, all with hot reload (Ctrl-C stops)
make sdk-bot     # in another terminal: run the SDK quickstart RandomBot vs the house
make bot         # older dev demo bot vs the house (prints a watch URL)
make mint        # just print a fresh bot API key (crbk_…)
make test        # fast gate: ruff + unit tests + svelte-check (server + SDK + frontend)
make e2e         # Playwright smokes: dashboard→watch→replay, and the SDK-fed onboarding flow
make down        # stop containers (keeps the DB volume)
make down-clean  # stop containers AND wipe the Postgres volume (clean slate)
```

`make dev`/`make demo` wrap the raw steps (`docker compose up -d db`, `alembic upgrade head`,
`uvicorn --reload --port 8001`, `npm run dev`); run them by hand if you prefer (see the Makefile,
`server/README.md`, `frontend/README.md`). `make sdk-bot`/`make bot`/`make e2e` need a running
stack (start `make dev` first — except `make e2e`, which starts its own).

## License

TBD.
