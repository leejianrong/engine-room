# ADR-0005: Stack — FastAPI + Postgres backend, TypeScript frontend

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
We need to commit to an implementation stack before protocol details harden. Answers QUESTIONS K1; constrains K2/K3. The transport is WebSocket (ADR-0002) and we will lean on an existing chess library (ADR-0006).

## Decision
- **Backend:** Python with **FastAPI** (Starlette WebSocket support built in).
- **Records datastore:** **PostgreSQL** (accounts, bots, game results/PGNs).
- **Frontend:** **TypeScript**, framework **Svelte or React — TBD** (see QUESTIONS N1). Does not block backend work.

## Alternatives considered
- Node/TS backend (single language front-to-back) — rejected in favor of Python because the canonical chess library (`python-chess`, ADR-0006) is Python and gives legality + SAN/UCI + PGN for free.
- Go/Elixir for high-concurrency WebSockets — stronger raw concurrency story, but overkill at MVP scale and slower to build; we run no engine code ourselves so CPU is light.

## Consequences
- Positive: FastAPI async handles our WebSocket fan-out at MVP scale; Python unlocks `python-chess`; Postgres is a safe, well-understood record store.
- Negative / costs: Python's GIL means a single process won't scale WebSockets indefinitely — but ADR-0002 already pins a game to one process, so we scale by running multiple processes/workers and sharding games across them (deferred, K2). Live game state is **not** a natural fit for Postgres; likely in-memory per-process at MVP, with Redis as a later option (→ QUESTIONS J1/J2).
- Follow-on questions opened: N1 (Svelte vs React), K2 (how games shard across workers), J1/J2 (live-state store), K3 (hosting target that must support long-lived WebSockets — rules out naive serverless).
