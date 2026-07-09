# ADR-0022: Onboarding flow + house bots

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Defines the "signup → first move" path and fixes a cold-start problem it exposes. Answers QUESTIONS L3; complements the SDK (ADR-0021) and matchmaking (ADR-0011/0012/0016).

## Decision

**Onboarding path (target: < 20 min):**
1. Sign in with GitHub (ADR-0013) → dashboard.
2. Create a bot → **API key shown exactly once** (ADR-0014) → copy.
3. `git clone <quickstart-repo>` → `pip install -r requirements.txt` (installs the `chessroom` SDK, ADR-0021).
4. Paste the key into `.env` (`CHESSROOM_KEY=...`) → `python random_bot.py`.
5. SDK connects, auto-queues, calls `choose_move(board)` (returns a random legal move) → bot is playing.
6. Dashboard links to the live spectator view (ADR-0015).

A dedicated minimal **quickstart template repo** (a ready `RandomBot` + README) is the newcomer's entry point; it depends on the published SDK rather than vendoring it.

**House bots (fixes cold start):** the platform runs a small stable of always-available **house/reference bots** (e.g. `house-random`, `house-minimax`) sitting in every time-control pool.
- Guarantees a newcomer's first bot gets an **immediate match** instead of hitting the ticket TTL on an empty pool (ADR-0016).
- House bots playing each other keep the **spectator dashboard alive with zero real users** (serves the "casually log on and watch" pitch).
- They are the SDK's example bots, so they double as living documentation.
- Owned by a platform account and rated normally; the same-owner exclusion (ADR-0016) does **not** block real users from being paired with them.

## Alternatives considered
- **No house bots** — rejected; a newcomer's first game would time out on an empty MVP platform (awful first impression) and spectators would see an empty lobby.
- **Vendoring the SDK into the quickstart** — rejected; the quickstart depends on the published package so upgrades are a version bump.
- **Minimax as the hello-world default** — rejected; `RandomBot` needs zero chess knowledge and is the true minimal example (minimax is the "level 2" sample).

## Consequences
- Positive: guaranteed, instant first game; a lively spectator experience from day one; example bots earn double duty as house bots.
- Negative / costs: house bots are always-on processes to operate/monitor; their ratings occupy the leaderboard (acceptable / expected).
- Follow-on questions opened: how many house bots and at what strength spread; should house-bot games be visually flagged as such in the lobby.

## Addendum (2026-07-09, V3): two house roles; ambient role deferred to V6
Building V3 (real matchmaking) split "house bot" into **two distinct roles**, and clarified when each lands:

- **Kind 2 — ephemeral greeter (built in V3).** Guarantees a newcomer's near-instant first game (the *instant-first-game* guarantee above). It is **not** a pool member: the matcher **synthesizes a house opponent on demand** for a ticket that has waited alone past a short per-pool solo-wait (the greeter is enabled for 3+0, `ER_MM_*`-tunable). This preserves the sessionless in-process house of V1/V2 and never crowds real-vs-real pairing.
- **Kind 1 — ambient pool-resident house bots (deferred to V6).** House bots that *sit in the pool* and are Elo-matched like users, **including against each other**, so the spectator lobby always shows a live game (the *never-empty-lobby-with-zero-users* guarantee above). This needs a **2nd house identity** (V3 ships only `bot_house_random`), tickets generalized to sessionless in-pool participants, and a re-enrollment lifecycle. Its payoff is the lobby — which is built in **V6** — so it lands there.

Net: with a single house identity and greeter-only, **V3 does not produce house-vs-house games**; the *instant-first-game* guarantee is met in V3, the *never-empty-lobby* guarantee arrives in V6. See docs/shaping/V3-plan.md (D-i).

## Addendum (2026-07-09, V6): Kind-1 ambient bots built — rated + persisted
Kind-1 landed with the lobby it feeds. An `AmbientSupervisor` (started/stopped by the app lifespan, `ER_AMBIENT_*`-tunable, off when `0`) keeps `N` (default 2) **house-vs-house** games live in the 3+0 pool: `house-random` vs a **second seeded identity `house-random-2`** (Alembic **0004**, data-only seed). They are created **outside** the matcher (never touching real-vs-real pairing / same-owner / anti-rematch / the greeter) but launched through the **normal `GameLauncher`**, so — per this ADR's "rated normally" intent and the V5 finalizer — they are **rated + persisted** (owner call, overriding the V6-plan's ★ unrated recommendation; house rating drift is accepted until a leaderboard exists). Each finished ambient game is **evicted from the in-memory registry** (its record + replay live in Postgres) so `_games` stays bounded under the endless stream, then a replacement spawns. Because ambient games share the two house identities and finish often, the finalizer now loads bot rows **`with_for_update`** in a fixed id order (no lost rating update / no deadlock). The open follow-on "should house games be visually flagged in the lobby" is **not** done — they simply show as `house-random`/`house-random-2` (a visual flag is later polish). See docs/shaping/V6-plan.md (D-g/D-h).

## Addendum (2026-07-09, V7): onboarding path realized; reference-bots reconciliation
The onboarding path (steps 3–6) is real. The **quickstart template** (`sdk/quickstart`: `random_bot.py` + `.env.example` + README + optional Dockerfile) delivers `git clone → uv sync → paste CHESSROOM_KEY into .env → uv run python random_bot.py → matched vs the house → watch on the V6 dashboard`; an **SDK-fed Playwright e2e** proves it end-to-end (the ADR-0023 smoke). The quickstart **depends on** the packaged `chessroom` SDK (path-installed pre-PyPI, ADR-0021 V7 addendum), not a vendored copy — as this ADR intended.

**Reference-bots-double-as-house-bots reconciliation (V7 O-1):** the SDK's `RandomBot`/`MinimaxBot` **mirror** the server house bots' move logic but are **not shared-imported** — the server must not depend on the SDK (ADR-0021 decoupling). So "the reference bots double as the house bots" holds by *shared behavior + documentation*, not a code merge; the server keeps its in-process, sessionless `game/house_bots.py`. Revisit only if house bots are ever run *as SDK WebSocket clients*. See docs/shaping/V7-plan.md.
