# Engine Room

A real-time matchmaking and spectating platform for **AI chess bots** — think "Chess.com for bots." Humans register bots; bots connect outward over a WebSocket to be matched by Elo and play **bot-vs-bot** games that anyone can watch live in the browser.

> **Status:** early build. The product design is fully specified (25 ADRs + wire protocol + PRD); implementation is underway on the MVP, sliced into V1–V7. **V1 (the walking-skeleton game thread) is in progress** — see [docs/shaping/V1-plan.md](docs/shaping/V1-plan.md).

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
- **Bot SDK:** `chessroom` Python package — a *separate* repo (depends only on the versioned protocol spec, ADR-0021); not in this repo.

## Try it out — watch a live match (one command)

```bash
make demo        # builds & runs db + backend + frontend + a looping demo bot (all in Docker)
```

Then open **http://localhost:5174** and paste the `game_…` id from the `demo-bot` logs
(`Watch it here: …`) into the box — the board updates move-by-move. `make down` stops everything.

Why a demo bot at all? There's **no lobby yet** (that's V6), and bots are external clients that
connect *to* the platform — so a match only exists once a bot seeks one. The demo bot
(`engine_room.devtools.demo_bot`) is a throwaway stand-in for the future `chessroom` SDK: it
mints a real API key, seeks a game (matched to a real opponent if one is queued, else the house
greeter), and prints the `game_id` to spectate.

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js, Docker. Run `make` (or `make help`)
to see every target.

```bash
make install     # once per clone: uv sync + npm install
make dev         # db + backend + frontend, all with hot reload (Ctrl-C stops)
make bot         # in another terminal: start games vs the house + print the watch URL
make mint        # just print a fresh bot API key (crbk_…) to use with your own client
make test        # fast gate: ruff + unit tests + svelte-check
```

`make dev`/`make demo` wrap the raw steps (`docker compose up -d db`, `alembic upgrade head`,
`uvicorn --reload --port 8001`, `npm run dev`); run them by hand if you prefer (see the Makefile,
`server/README.md`, `frontend/README.md`).

## License

TBD.
