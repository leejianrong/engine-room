# CONTEXT

Living design context for the AI chess bot matchmaking & spectating platform.
Source of truth for decisions is the ADRs in `docs/adr/`; this file is the narrative + glossary that ties them together. The bot↔server wire contract lives in [PROTOCOL.md](PROTOCOL.md).

Product one-liner: _A real-time matchmaking and spectating platform for AI bots / algorithmic chess engines to compete against each other._

---

## Ubiquitous language (glossary)
_(filled in as we agree on terms during grilling)_

| Term | Meaning | Status |
|------|---------|--------|
| User | A human account. Owns bots, manages settings, spectates; never plays moves. | 🟢 |
| Bot | First-class persistent entity owned by a User: identity, name, description, **Elo rating** (MVP), stats. One User owns many Bots. | 🟢 |
| Rating (Elo) | Per-Bot integer Elo; init 1200; updates only on FINISHED games; ABORTED games don't count. Single global rating at MVP. | 🟢 |
| Pool | A matchmaking queue scoped to one time control; Elo pairing happens within a pool. | 🟢 |
| Spectator | Anonymous (no login) human viewer of a live game over a read-only SSE stream. | 🟢 |
| Catch-up snapshot | The current game state (FEN, clocks, move list, players/ratings) sent to a spectator on join, before live SSE events. | 🟢 |
| SDK | Official `engineroom` Python package (own repo, **uv + pyproject.toml**); user subclasses `Bot`, implements `choose_move`; SDK owns transport/auth/reconnect/protocol. | 🟢 |
| UCI bridge | Client-side SDK tool: a Bot that delegates move choice to a local UCI engine subprocess via `python-chess`. Never runs server-side. | 🟢 |
| House bot | Platform-owned reference bot always present in pools; guarantees newcomers a match and keeps the spectator lobby lively. | 🟢 |
| Protocol spec | The public, versioned wire-protocol contract the SDK and server both conform to (shared contract, not shared code). | 🟢 |
| Session | One continuous authenticated WebSocket connection for a Bot. Many per Bot over time; at most one live at a time. Authenticated at the handshake via the bot's API key. | 🟢 |
| API key (bot) | One rotatable per-Bot bearer secret; stored hashed, shown once, sent in the `Authorization` header at the WebSocket handshake. Rotation instantly kills the old key. | 🟢 |
| Game | A single bot-vs-bot contest with one Result. The MVP unit. "Match"/"Tournament" reserved for future multi-game constructs. | 🟢 |
| Seat | A side (White/Black) in a Game, bound to a Bot for the game's duration; filled by whichever Session is currently live. | 🟢 |
| MatchmakingTicket | A Bot's request to play (carries desired time control); the QUEUED pre-Game state; becomes a Game on pairing. | 🟢 |
| your_turn | Server→bot WebSocket event telling a bot it is on move, carrying current state + clock. | 🟢 |
| Flag | A bot's clock reaching zero → loss on time; auto-detected server-side. | 🟢 |
| Reconnect | A bot may rejoin a live game anytime via a fresh handshake (same key). No separate forfeit window — the **game clock** governs; heartbeat detects only mutual abandonment (ADR-0025). | 🟢 |
| Seek | A message a bot sends over its WebSocket to enter matchmaking, carrying the desired time control (ADR-0025). | 🟢 |
| Bot's clock eats latency | A bot's clock includes its own network round-trip (clock runs server-send → server-receive). | 🟢 |
| UCI (move) | Long-algebraic coordinate move on the wire (`e2e4`, `e7e8q`). Canonical wire format. | 🟢 |
| SAN | Standard Algebraic Notation (`Nf3`, `O-O`). Display/PGN only, server-rendered from UCI. | 🟢 |
| Result | Game outcome: `WHITE_WINS` / `BLACK_WINS` / `DRAW` / `ABORTED`. | 🟢 |
| Termination reason | Why a game ended (checkmate, timeout, resignation, stalemate, agreement, …). Separate field from Result. | 🟢 |

## Domain model
_(ratified in ADR-0009 (entities) and ADR-0010 (Game lifecycle))_

```
User (1) ──owns──▶ (N) Bot ──has over time──▶ (N) Session   [≤1 live per Bot]
                      │
                      └─ fills ─▶ Seat (White|Black) ──in──▶ Game (2 seats)
Bot ──requests──▶ MatchmakingTicket ──pairs──▶ Game
```

Game lifecycle (state machine, ADR-0010):
`QUEUED` (on ticket) → `PAIRED` → `IN_PROGRESS` → `FINISHED` (has Result) | `ABORTED` (no result).
A withdrawn ticket is `CANCELED` (not a Game). Disconnect is a seat substate *within* IN_PROGRESS, not a Game state.

Invariants (from ADRs):
- The **server** is the single source of truth for clock (ADR-0003) and board legality (ADR-0006, via `python-chess`).
- A Game **seat is bound to a Bot, not a Session**; the live Session is swappable transport → reconnect resumes the same seat (ADR-0004, ADR-0009).
- **One live Session per Bot ⟹ a Bot is in at most one active Game at a time** (resolves E6).
- Timeout detection is **server-side and automatic**, not opponent-claimed (ADR-0003).
- Terminal Game states (FINISHED, ABORTED) are immutable.
- **Two real-time transports, split by trust:** bots ↔ server = **authenticated bidirectional WebSocket** (ADR-0002/0014); spectators = **anonymous read-only SSE** (ADR-0015).
- A Game is pinned to one worker (ADR-0002); spectators can connect to any worker ⟹ multi-worker deployment needs **internal pub/sub (Redis)** to fan game events out (ADR-0015, ties K2).
- **Storage split:** live game state = **in-memory in the game's worker**; durable records (users, bots, key hashes, ratings, results, PGNs) = **Postgres**, written at finalization in a **single transaction** (ADR-0018, ADR-0025).
- **No Redis in the MVP** (ADR-0025): single-process MVP uses **in-memory queues + in-process pub/sub behind `MatchmakingQueue`/`PubSub` interfaces**; Redis enters only at multi-worker scale-out (ADR-0020).
- **Accepted MVP risk:** a worker crash loses its in-progress games (I3) — not recoverable until live-state persistence is added later.
- Matchmaking **never pairs two bots of the same owner** (anti rating-farming, ADR-0016) — **except house bots, which are exempt** and may play each other (ADR-0025).
- **The game clock is the sole arbiter of a bot's time** (ADR-0025): no separate reconnect-window; a disconnected bot loses only by flagging (or illegal move); a heartbeat detects only *mutual* abandonment → ABORT.
- **Bots queue by sending a `seek` (with time control) over their WebSocket** (ADR-0025); one persistent socket covers connect→seek→play. Management = REST, spectating = SSE.
- **5 bots per User** (MVP; a Premium tier can raise it later). One bot plays one game at a time ⟹ ≤5 concurrent games/user (ADR-0019).
- **MVP = single game-worker process** (pinning trivially satisfied). Scale path: Redis-bridged edge/home workers, where the **bot event bus == spectator fan-out bus** (ADR-0020). Game state stays pinned; sockets need not be colocated.
- **SDK ↔ server are decoupled**: separate repos, sharing only a public **versioned protocol spec**; handshake carries a protocol version (ADR-0021).
- **House bots are load-bearing for MVP UX**: always in pools so newcomers get an instant first game and the spectator lobby is never empty (ADR-0022).

## Decisions log
_(one line per settled decision; deep rationale lives in the linked ADR)_

| # | Decision | ADR |
|---|----------|-----|
| 1 | MVP time-control floor = **Blitz (3+0, 5+0)**; Bullet deferred | [ADR-0001](../adr/0001-time-control-floor.md) |
| 2 | Bot↔server transport = **persistent WebSocket** (server pushes turns; reused for spectators) | [ADR-0002](../adr/0002-transport-websocket.md) |
| 3 | **Server-authoritative clock**; bot eats its own network latency; no RTT compensation at MVP | [ADR-0003](../adr/0003-clock-bot-eats-latency.md) |
| 4 | Mid-game disconnect = **reconnect window, clock keeps running**; else forfeit | [ADR-0004](../adr/0004-disconnect-reconnect-window.md) |
| 5 | Stack = **FastAPI + Postgres** backend, **TypeScript** frontend (Svelte/React TBD) | [ADR-0005](../adr/0005-stack-fastapi-postgres-ts.md) |
| 6 | Rules authority = **`python-chess`** (legality, mate/draw detection, PGN, UCI↔SAN) | [ADR-0006](../adr/0006-rules-authority-python-chess.md) |
| 7 | Move wire format = **UCI coordinate** (single canonical); SAN for display only | [ADR-0007](../adr/0007-move-wire-format-uci.md) |
| 8 | **Result + termination-reason** vocabulary; bots may **resign / offer draw** | [ADR-0008](../adr/0008-result-and-termination-vocabulary.md) |
| 9 | Core entities: **User→(N)Bot→(N)Session**; Bot is first-class; Seat bound to Bot; "Game" not "Match" | [ADR-0009](../adr/0009-core-domain-entities.md) |
| 10 | **Game lifecycle** = QUEUED→PAIRED→IN_PROGRESS→FINISHED\|ABORTED (explicit state machine) | [ADR-0010](../adr/0010-game-lifecycle-state-machine.md) |
| 11 | **Elo pairing + per-Bot ratings at MVP** (widening-window); rating updates on FINISHED only | [ADR-0011](../adr/0011-elo-matchmaking-and-ratings.md) |
| 12 | Matchmaking policy: **pools per time control**, **anonymous auto-pairing only**, queue TTL give-up, **anti-rematch cooldown** | [ADR-0012](../adr/0012-matchmaking-pool-and-queue-policy.md) |
| 13 | Human auth = **GitHub OAuth** via **FastAPI-Users**, modular for Google/password later | [ADR-0013](../adr/0013-human-auth-github-oauth.md) |
| 14 | Bot auth = **one rotatable API key/Bot**, hashed, sent at WS handshake; instant-invalidate on rotation; reconnect uses same key | [ADR-0014](../adr/0014-bot-api-keys-and-handshake.md) |
| 15 | Spectating = **SSE**, **anonymous**, **no broadcast delay**, catch-up snapshot + replay on join | [ADR-0015](../adr/0015-spectator-delivery-sse.md) |
| 16 | **MVP fine-print batch**: session newest-wins, illegal-move=forfeit, soft anti-rematch, auto-draws (no claim), same-owner exclusion, + matchmaking numbers | [ADR-0016](../adr/0016-mvp-defaults-batch.md) |
| 17 | Frontend framework = **Svelte** (flip to React on preference) | [ADR-0017](../adr/0017-frontend-svelte.md) |
| 18 | Persistence: **in-memory live state**, **Postgres records** at finalization, **Redis pub/sub only**, **PGNs at MVP** | [ADR-0018](../adr/0018-persistence-model.md) |
| 19 | Abuse: **5 bots/user** (Premium lever later), rate-limit connect/queue/messages, **soft griefing cooldowns**, GitHub-account human gate | [ADR-0019](../adr/0019-abuse-prevention.md) |
| 20 | Topology: **single game-process at MVP**; scale via **Redis-bridged edge/home worker** reusing the spectator bus (global Redis queues) | [ADR-0020](../adr/0020-worker-assignment-topology.md) |
| 21 | **Python SDK** + **client-side UCI bridge**; SDK is its own repo, depends only on a versioned protocol spec; handshake carries protocol version | [ADR-0021](../adr/0021-client-sdk-and-uci-bridge.md) |
| 22 | Onboarding: GitHub → key-once → clone quickstart → run; **house bots** always in pools guarantee a first match + a live lobby | [ADR-0022](../adr/0022-onboarding-and-house-bots.md) |
| 23 | **MVP scope & success**: demoable slice, v1 in/out line, primary user = AI/CS student (SDK is the hero path) | [ADR-0023](../adr/0023-mvp-scope-and-success.md) |
| 24 | Bot tooling = **uv + pyproject.toml** (hero path); **container optional**, not default | [ADR-0024](../adr/0024-bot-tooling-uv-and-optional-container.md) |
| 25 | **A2 consistency pass**: house-bot exemption · no Redis in MVP (behind interfaces) · clock is sole arbiter · queue-over-WS · atomic finalization | [ADR-0025](../adr/0025-a2-consistency-pass.md) |
| 26 | **Wire protocol v1.0 drafted** — bot↔server contract; resolves B5 (full FEN/turn), I4 (ply idempotency), C8 (clock fields) | [PROTOCOL.md](PROTOCOL.md) |

## MVP definition (ADR-0023)
**Demoable slice (v1-done):** a developer signs in with GitHub, creates a bot (key shown once), clones the quickstart, runs it, and within minutes watches it get matched against a house bot and play a full **3+0 Blitz** game to a real result — live on the public dashboard, clock enforced server-side, PGN saved to the bot's profile.

**Primary user:** the AI/CS student writing their first bot from scratch. Success = zero → live, watchable game in minutes, no protocol plumbing. ⟹ the **SDK / quickstart / RandomBot path is the hero flow**; UCI bridge is secondary polish.

**Deferred post-v1:** Bullet + RTT compensation · multi-worker scale + crash recovery · tournaments · Google/password auth · non-Python SDKs · Premium tier · leaderboard UI (data exists) · per-TC ratings · direct challenges.

## Constraints & assumptions carried from REQS.md
- Bot-vs-bot only; humans manage settings and spectate, never play moves.
- No hosting/execution of user code (MVP) — bots connect outward to us.
- No native legacy UCI/XBoard protocol on the server.
- No anti-cheat / code-originality verification.
- Server must enforce the game clock; timeout = loss.

## Open threads
_(the live edge of the conversation — what we're currently grilling)_

- ✅ **Real-time game spine** (transport, latency floor, clock, disconnect) — settled, ADR-0001..0004.
- ✅ **Rules, wire format, stack, outcomes** — settled, ADR-0005..0008.
- ✅ **Core domain model + Game lifecycle** — settled, ADR-0009..0010.
- ✅ **Matchmaking (Section E)** — settled, ADR-0011..0012 (Elo + ratings, per-TC pools, anonymous auto-pairing, TTL give-up, anti-rematch). Numbers deferred to E8.
- ✅ **Auth & identity (Section G)** — settled, ADR-0013..0014 (GitHub OAuth via FastAPI-Users; per-Bot rotatable API key at the WS handshake). Resolves B6, I6.
- ✅ **Spectating (Section F)** — settled, ADR-0015. Opened F3 (resolved in ADR-0016) + F4/K2 (fan-out pub/sub).
- ✅ **Small-decisions batch** — cleared, ADR-0016 (A6, B7, E7, E8, F3, I7, D6, D7, D8, H5) + ADR-0017 (N1→Svelte).
- ✅ **Persistence (Section J)** — settled, ADR-0018 (in-memory live, Postgres records, Redis pub/sub only, PGNs at MVP).
- ✅ **Abuse prevention (Section H) + topology (K2)** — settled, ADR-0019..0020.
- ✅ **Adapter / DX (Section L)** — settled, ADR-0021..0022 (Python SDK, client-side UCI bridge, decoupled repo, onboarding + house bots). Resolves B6.
- ✅ **MVP scope & success (Section M)** — settled, ADR-0023 (demoable slice, v1 boundary, AI/CS-student primary user).
- ✅ **Bot tooling** — settled, ADR-0024 (uv + pyproject.toml; container optional).
- 🏁 **Grilling complete.** All 13 backlog sections settled; 24 ADRs; all 3 REQS open questions closed.
- Remaining open (non-blocking build-time / tuning details, tracked in QUESTIONS.md): F4 (fan-out limits), worker failover/rebalance, tournament nice-to-have (deferred), PGN retention + history API shape, D4 (standard-position-only confirm), house-bot count/strength, protocol-spec location/versioning.
