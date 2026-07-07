# PRD: AI Chess Bot Matchmaking & Spectating Platform (MVP / v1)

Status: ready-for-agent
Date: 2026-07-07
Primary source of truth for decisions: the ADRs in `docs/adr/` and the wire contract in [PROTOCOL.md](../PROTOCOL.md). This PRD synthesizes them into a build brief; it does not re-derive them. Terms are used per the glossary in [CONTEXT.md](../CONTEXT.md).

---

## Problem Statement

There is no modern, low-friction, casual home for automated chess players — a "Chess.com for bots."

- **For bot creators** (software engineers, AI/CS students, chess-engine hobbyists): testing a custom chess bot against other bots today means standing up complex local servers, wiring cumbersome legacy desktop protocols (UCI/XBoard), or entering slow, formal computer-chess tournaments. There is no place to write a bot, point it at a service, and immediately see it ranked and playing live against others.
- **For spectators** (chess fans, tech enthusiasts): watching computer chess (e.g. TCEC) feels rigid and unapproachable. There is no central, lively site where anyone can open a browser and watch bots clash in real time, with clean visuals and no setup.

The underlying friction is that existing systems are trapped in 1990s desktop-first architecture, making automated matchmaking high-effort to set up and unpleasant to watch.

**The person we are building for first (ADR-0023):** the AI/CS student writing their first chess bot from scratch. Today, the gap between "I have an idea for a move-picking function" and "my bot is playing a ranked game someone can watch" is measured in days of plumbing. It should be minutes.

---

## Solution

A hosted, real-time platform where humans register **Bots**, and those bots connect *outward* to us to be matched and to play **bot-vs-bot** games that anyone can watch live in a browser.

The MVP delivers one complete, demoable end-to-end slice (ADR-0023):

> A developer signs in with GitHub, creates a **Bot** (and receives a rotatable API key, shown once), clones the quickstart, runs it, and within minutes watches their bot get matched against a **house bot** and play a full **3+0 Blitz** game to a real result — live on a public spectator dashboard, with the clock enforced server-side and the **PGN** saved to the bot's profile.

How the pieces fit:

- **Humans** manage everything over a normal web app (GitHub OAuth login, create/manage bots, rotate keys, view history). Humans never play moves.
- **Bots** hold a single authenticated **WebSocket** to the server. Over that one socket a bot connects, **seeks** a game (choosing its time control), and plays — the server pushes `your_turn`, the bot replies with a `move`. The server is the sole authority for the clock and for move legality.
- The official **`chessroom` Python SDK** hides all of that: a user subclasses `Bot` and implements `choose_move`; the SDK owns transport, auth, reconnect, heartbeats, and protocol (de)serialization. A **UCI bridge** ships with the SDK so an existing engine (e.g. Stockfish) can play without a rewrite — entirely client-side.
- **House bots** are always present in the pools, so a newcomer gets an instant first game and the spectator lobby is never empty.
- **Spectators** (anonymous, no login) watch live over a read-only **SSE** stream: a catch-up snapshot on join, then live moves, with replay from move 1.

The MVP runs as a **single game-worker process** (Postgres for durable records; no Redis yet). Live game state lives in memory in that worker; durable records (users, bots, key hashes, ratings, results, PGNs) are written to Postgres in one transaction at game finalization.

---

## User Stories

### Human account & identity
1. As a bot creator, I want to sign in with my GitHub account, so that I can get started without creating and remembering a new password.
2. As a bot creator, I want a profile that persists across sessions, so that my bots and their history are always tied to me.
3. As a bot creator, I want my GitHub account to be the thing that gates access, so that the platform has a basic human-authenticity signal without me solving captchas.
4. As the platform, I want human auth to be modular (GitHub now, Google/password later), so that adding sign-in methods later does not require re-architecting identity.

### Managing bots
5. As a bot creator, I want to create a Bot with a name and description, so that it has a first-class identity that others can recognize on the dashboard.
6. As a bot creator, I want to own multiple Bots under one account, so that I can run several different engines or experiments in parallel.
7. As a bot creator, I want to be limited to a sane number of Bots (5 at MVP), so that the platform stays fair and un-spammable — and I understand a Premium tier may raise this later.
8. As a bot creator, I want to see each of my Bots' current Elo rating and basic win/loss record, so that I can tell whether my changes are making it stronger.
9. As a bot creator, I want to delete a Bot I no longer want, so that my account stays tidy.

### Bot credentials
10. As a bot creator, I want to generate a secret API key for a Bot, so that my code can authenticate to the platform as that Bot.
11. As a bot creator, I want the key shown to me exactly once at creation, so that it is never recoverable from the server in plaintext if my account is later compromised.
12. As a bot creator, I want to rotate a Bot's key, so that I can recover if the key leaks.
13. As a bot creator, I want key rotation to instantly invalidate the old key, so that a leaked key stops working the moment I replace it.
14. As the platform, I want keys stored only as hashes, so that a database leak does not expose usable credentials.

### Getting a first bot running (the hero path)
15. As an AI/CS student, I want an official Python SDK, so that I can write a bot by implementing one method instead of hand-rolling a WebSocket protocol.
16. As an AI/CS student, I want to subclass a `Bot` class and implement `choose_move(board)`, so that I work with a familiar `python-chess` board and never touch the wire format.
17. As an AI/CS student, I want a clonable quickstart project (a runnable `RandomBot`), so that I can get from zero to a live game by editing one file.
18. As an AI/CS student, I want the quickstart to use `uv` + `pyproject.toml`, so that setup is one modern, reproducible command and not a dependency scavenger hunt.
19. As an AI/CS student, I want the SDK to own transport, auth, reconnect, and heartbeats, so that I never have to think about connection management.
20. As a chess-engine hobbyist, I want a client-side UCI bridge shipped with the SDK, so that I can point my existing engine (e.g. Stockfish) at the platform without rewriting it.
21. As a hobbyist, I want the UCI bridge to run entirely on my machine, so that I keep my engine private and the platform never needs my binary.
22. As a bot creator, I want the SDK to live in its own repo and depend only on a public, versioned protocol spec, so that I can upgrade the SDK and the server independently.

### Connecting & session lifecycle
23. As a bot, I want to open one authenticated WebSocket and keep it, so that the server can push my turns to me in real time.
24. As a bot, I want to authenticate with my API key in the `Authorization` header at the WebSocket handshake, so that credentials are established per-connection and never sent per-message or in a URL.
25. As a bot, I want the handshake to exchange a protocol version, so that an incompatible SDK/server pair fails fast and clearly instead of misbehaving.
26. As a bot, I want a new authenticated connection to cleanly replace my previous one (newest-wins), so that a restart or redeploy does not leave me locked out by a stale session.
27. As the platform, I want at most one live Session per Bot, so that a Bot is unambiguously in at most one active Game at a time.

### Seeking & matchmaking
28. As a bot, I want to send a `seek` over my socket carrying my desired time control, so that one connection covers connect → seek → play with no separate queue endpoint.
29. As a bot, I want to be placed in the pool for my chosen time control (3+0 or 5+0), so that I only play games at the speed I asked for.
30. As a bot, I want to be paired with an opponent near my Elo, so that games are competitive rather than blowouts.
31. As a new bot with a default rating, I want to be matched quickly against a house bot when no human opponent is available, so that my very first run produces a real game.
32. As a bot, I want to cancel a seek, so that I can stop waiting if I change my mind.
33. As a bot, I want my seek to expire after a bounded wait (TTL) rather than hang forever, so that I get a clear "no match" outcome and can retry.
34. As a bot creator, I want the platform to never pair two of *my own* bots against each other, so that I cannot (even accidentally) farm my own rating.
35. As the platform, I want an anti-rematch cooldown, so that the same two bots are not repeatedly paired back-to-back.

### Playing a game
36. As a bot, I want a `game_start` telling me my color, my opponent (name + rating), the time control, and the initial position, so that I have everything I need before the clock starts.
37. As a bot, I want the server to push `your_turn` with the full current FEN, the opponent's last move, and both clocks every time it is my move, so that I am stateless and never have to keep the board in sync myself.
38. As a bot, I want to reply with a `move` in UCI coordinate notation, so that there is exactly one canonical, unambiguous move format on the wire.
39. As a bot, I want a `move_ack` confirming my move was received and applied, so that I know whether to resend after a network blip.
40. As a bot, I want to safely resend the identical move (same game + ply + uci) if I miss an ack, so that a dropped ack never causes a double-move or a self-forfeit.
41. As a bot, I want to resign, so that I can concede a lost position instead of playing it out.
42. As a bot, I want to offer a draw (piggybacked on a move or standalone) and to accept an opponent's offer, so that agreed draws are possible.
43. As a bot, I want a normal move to implicitly decline a standing draw offer, so that I do not need a separate decline message.
44. As a bot, I want the server to auto-apply standard draws (stalemate, insufficient material, threefold/fivefold repetition, fifty/seventy-five-move), so that I never have to detect or claim them myself.
45. As a bot, I want the server to be the single authority on move legality (via `python-chess`), so that there is never a dispute about whether a move was legal.
46. As a bot, I want an illegal or unparseable move at the current ply to end the game as a forfeit with a clear termination reason, so that the rules are unambiguous and I learn my bot has a bug.
47. As a bot, I want non-move junk (unknown types, malformed JSON) to be ignored with an error rather than ending my game, while my clock keeps running, so that a stray log line does not forfeit me.

### Clock & time
48. As a bot, I want the server to be the single source of truth for the clock, so that neither side can cheat time and there are no clock-sync disputes.
49. As a bot, I want my clock to run from the instant the server sends `your_turn` until it receives my move, so that the rule ("you eat your own network latency") is simple and well-defined.
50. As a bot, I want to lose on time automatically and instantly when my clock hits zero (flag), detected server-side, so that timeouts are enforced without my opponent having to claim them.
51. As a bot, I want a timeout-vs-insufficient-material position scored as a draw, so that edge-case endings follow real chess rules.
52. As the platform, I want the increment path modeled now (`{base, increment}`) even though MVP increment is 0, so that adding incremented time controls later needs no protocol change.

### Reconnection & failure
53. As a bot, I want to reconnect anytime with the same key and resume my in-progress game, so that a crash or redeploy mid-game does not automatically lose it.
54. As a bot, I want the `welcome` on reconnect to carry my active game's full state (FEN, ply, clocks, whose turn, standing draw offer), so that I can resume without external bookkeeping.
55. As a bot, I want my game clock to keep running while I am disconnected, so that the rules are consistent whether I am connected or not — the clock is the sole arbiter of my time.
56. As a bot, I want to lose only by flagging (or by an illegal move) while disconnected — never by a separate hidden "reconnect window" — so that the timing rule is the one I already understand.
57. As the platform, I want a heartbeat that only detects *mutual* abandonment (both seats gone) and aborts such games with no result, so that a game nobody is playing does not linger, but a single dropout is still governed purely by the clock.

### Results, ratings & history
58. As a bot, I want a `game_over` carrying the result, the termination reason, the final FEN, the full PGN, and my rating change, so that my client has a complete record of how the game ended.
59. As a bot creator, I want each Bot to start at 1200 Elo and update only on FINISHED games, so that ratings reflect real completed play and aborted games do not distort them.
60. As a bot creator, I want the PGN of every finished game saved to my Bot's profile, so that I can replay and analyze my bot's games later.
61. As a bot creator, I want a read-only game-history / win-loss API for my bots, so that I (or a future leaderboard UI) can show a bot's record.
62. As the platform, I want all durable records (result, rating change, PGN) written in a single transaction at finalization, so that a bot's history and rating can never disagree.

### Spectating
63. As a spectator, I want to open the site with no login and see a list of active games, so that I can start watching immediately.
64. As a spectator, I want each active-game entry to show both bots (name + rating), the time control, move count, and side-to-move, so that I can pick an interesting game.
65. As a spectator, I want to open a game and see the board update move-by-move in real time without refreshing, so that watching feels live.
66. As a spectator, I want a catch-up snapshot on join (current FEN, clocks, move list, players/ratings), so that I see the correct current state even if I join mid-game.
67. As a spectator, I want to replay the game from move 1, so that I can catch up on what already happened.
68. As a spectator, I want the stream to auto-reconnect if my connection blips, so that I do not have to manually refresh to keep watching.
69. As a spectator, I want live game data delivered with no artificial broadcast delay, so that I see moves as they happen.

### Abuse resistance
70. As the platform, I want to rate-limit connects, seeks, and inbound messages, so that a single client cannot flood the system.
71. As the platform, I want to disconnect a client that floods messages past the limit, so that abusive connections are shed rather than served.
72. As the platform, I want to track per-bot disconnect/abort/illegal-move rates and apply soft escalating cooldowns to repeat offenders, so that griefing is discouraged without hard-banning honest buggy bots.
73. As the platform, I want the 5-bots-per-user cap plus one-game-per-bot to bound a single user to at most 5 concurrent games, so that no account can monopolize capacity.

### House bots & onboarding
74. As a newcomer, I want house bots always present in the pools, so that my first seek always finds a game.
75. As a spectator, I want house bots keeping games running, so that the lobby is never empty when I arrive.
76. As the platform, I want the SDK's reference bots to double as house bots, so that the house bots exercise the same public path real users do.

---

## Implementation Decisions

These consolidate the ADRs. Where a decision has an ADR, it is cited; the ADR holds the rationale. No file paths or code are prescribed here.

### Architecture & stack
- **Backend:** Python + **FastAPI**; **Postgres** for durable records; **TypeScript** frontend in **Svelte** (ADR-0005, ADR-0017). Chess rules authority is **`python-chess`** — legality, mate/draw detection, PGN generation, UCI↔SAN rendering (ADR-0006).
- **Two real-time transports, split by trust boundary** (ADR-0002, ADR-0014, ADR-0015): bots ↔ server is an **authenticated, bidirectional WebSocket**; spectators use an **anonymous, read-only SSE** stream. Human/bot management is REST.
- **Topology:** MVP is a **single game-worker process** — game pinning is trivially satisfied and no cross-worker routing is needed (ADR-0020). **No Redis in the MVP** (ADR-0025): in-memory queues and in-process pub/sub sit **behind `MatchmakingQueue` and `PubSub` interfaces** so a Redis-bridged multi-worker deployment can drop in later without touching call sites.
- **Storage split** (ADR-0018, ADR-0025): live game state (board, clocks) is **in-memory in the game's worker**; durable records (users, bots, key hashes, ratings, results, PGNs) are **Postgres**, written **at finalization in a single transaction**. **Accepted MVP risk:** a worker crash loses its in-progress games (I3), not recoverable until live-state persistence is added post-v1.

### Domain model & lifecycle
- Entities (ADR-0009): **User (1) → (N) Bot → (N) Session** over time, with **≤1 live Session per Bot**. A **Bot** is first-class and persistent (identity, name, description, Elo, stats). A **Seat** (White/Black) is bound to a **Bot**, not a Session — so the live socket is swappable and reconnect resumes the same seat. "Game" is the single-contest unit; "Match"/"Tournament" are reserved for future multi-game constructs.
- **Game lifecycle state machine** (ADR-0010): `QUEUED` (on a MatchmakingTicket) → `PAIRED` → `IN_PROGRESS` → `FINISHED` (has Result) | `ABORTED` (no Result). A withdrawn ticket is `CANCELED` (a ticket outcome, not a Game). Disconnect is a **seat substate within IN_PROGRESS**, not a Game state. Terminal states are immutable.
  - `PAIRED → IN_PROGRESS`: both bots present; server sends White's first `your_turn` and White's clock starts.
  - `PAIRED → ABORTED`: a bot fails to ready within the **start-grace window** (~10s, tunable — ADR-0016 E7).
  - `IN_PROGRESS → FINISHED`: any decisive/draw termination. Single-side disconnect is a **forfeit → FINISHED**.
  - `IN_PROGRESS → ABORTED`: only when no fair result exists (both seats drop, or server fault).

### Matchmaking & ratings
- **Elo-based pairing within per-time-control pools**, single global rating per Bot at MVP (ADR-0011, ADR-0012). **Anonymous auto-pairing only** — no challenge-by-name at MVP.
- MVP defaults (ADR-0016 E8, tunable with data): initial rating **1200**; K-factor **32 → 16 after 30 games**; pairing window **±100, widening +100 per 10s, uncapped after 60s**; seek **TTL 120s**; pair when **≥2** compatible bots; **soft** anti-rematch cooldown.
- **Same-owner exclusion:** matchmaking never pairs two bots of the same User (ADR-0016) — **except house bots, which are exempt** and may play each other (ADR-0025). Rating updates on **FINISHED only**; ABORTED never affects rating.

### Auth & credentials
- **Human auth: GitHub OAuth via FastAPI-Users**, modular for Google/password later (ADR-0013).
- **Bot auth: one rotatable API key per Bot**, stored hashed, shown once, prefixed token; sent as `Authorization: Bearer <key>` **on the WebSocket upgrade** — not per-message, not in the query string (ADR-0014). Rotation regenerates and **instantly invalidates** the old key. Reconnect uses the same key; the server re-binds the Bot's active seat. **Newest-wins:** a new authenticated handshake replaces (and closes) the prior live Session.

### Bot WebSocket protocol (the contract)
- The full wire contract is **[PROTOCOL.md](../PROTOCOL.md) v1.0** and is the authoritative spec for this surface. Endpoint `wss://<host>/api/bot/v1` (major version in the path); UTF-8 JSON text frames; durations in integer **milliseconds**; moves in **lowercase UCI**; colors `"white"`/`"black"`.
- Message set: `hello`/`welcome` (handshake + protocol version + reconnect payload), `seek`/`seek_ack`/`seek_cancel`/`seek_ended`, `game_start`, `your_turn`/`move`/`move_ack`, `resign`, `draw_offer`/`draw_accept`, `game_over`, `ping`/`pong`, `error`.
- **State on the wire** (resolves B5, C8): `your_turn` carries the **full FEN every turn** (stateless for the bot), the opponent's `last_move`, both clocks as remaining ms, `your_color`, and `opponent_draw_offer`. Clocks are the remaining ms **at the instant the server sent `your_turn`**; the side-to-move's clock runs from that send instant to server-receipt of the move; increment (0 at MVP) is credited after the move applies.
- **`ply`-anchored idempotency & ordering** (resolves I4, PROTOCOL §9): a `move` applies only if `move.ply == expected_ply`; a matching-uci resend at an already-applied ply re-acks **without re-applying**; a stale/conflicting lower ply is ignored and **never penalized**; a future ply returns `INVALID_PLY`. Only an illegal move **at the current ply** forfeits.
- **Heartbeat** (PROTOCOL §10): server `ping` on an interval (~10s default), client `pong`; a missed-liveness peer (~30s default) is treated as disconnected. Liveness detects **only mutual abandonment** (both seats gone → ABORTED); a single dropout is governed purely by the clock.
- **Error codes** (PROTOCOL §11): `UNAUTHORIZED`, `VERSION_UNSUPPORTED` (fatal); `RATE_LIMITED`, `INVALID_MESSAGE`, `NOT_YOUR_TURN`, `INVALID_PLY`, `NO_ACTIVE_GAME` (non-fatal).

Reconnect state shape (from the drafted protocol, encodes the resume contract precisely):
```json
"active_game": {
  "game_id": "game_abc", "your_color": "white",
  "fen": "....", "ply": 4, "last_move": { "uci": "e7e5", "san": "e5" },
  "clocks": { "white_ms": 171200, "black_ms": 176500 },
  "opponent_draw_offer": false, "to_move": "white"
}
```

### Results & termination vocabulary
- Two separate fields (ADR-0008): **Result** ∈ `white_wins | black_wins | draw | aborted`; **termination reason** ∈ `checkmate, timeout, resignation, illegal_move, disconnect_forfeit, stalemate, insufficient_material, threefold_repetition, fifty_move, agreement, aborted`.
- `game_over` carries result, termination, final FEN, full PGN, and this bot's Elo change (absent for `aborted`).

### SDK & developer experience
- **Official `chessroom` Python SDK**, pip-published, in its **own repo**, depending only on the public versioned protocol spec — never server code (ADR-0021). Framework-style: subclass `Bot`, implement `choose_move(board) -> move`. The SDK owns transport, handshake/auth, reconnect, heartbeats, and (de)serialization.
- **Client-side UCI bridge** ships with the SDK: a `Bot` whose `choose_move` delegates to a local UCI engine subprocess via `python-chess`'s `chess.engine`. Never server-side (respects the REQS out-of-scope line).
- **Tooling:** `uv` + `pyproject.toml` is the hero path; a container is an **optional**, non-default path (ADR-0024).
- **Onboarding** (ADR-0022): GitHub → create bot (key shown once) → clone quickstart → run → matched vs a house bot. **House bots** are always in pools (the SDK's reference bots double as house bots).

### Spectating
- **Anonymous, read-only SSE** (ADR-0015), separate from the bot WebSocket. On join: a **catch-up snapshot** (FEN + clocks + move list + players/ratings), then live move events; **replay from move 1** is supported. **No artificial broadcast delay** (nothing to leak in bot-vs-bot).
- **Active-games lobby** shows both bots (name + rating), time control, move count, side-to-move; delivered by **REST poll at MVP** (a lobby SSE is a later refinement — ADR-0016 F3).

---

## Testing Decisions

**What makes a good test here:** it asserts on **externally observable behavior at a public contract**, never on internal state or private methods. For this system that means: given a sequence of wire messages (or HTTP/SSE interactions), assert on the wire messages / responses / persisted records that come back — not on how the matchmaker, clock, or board are implemented internally. Tests written this way survive refactors of the in-memory engine, the queue, and the persistence layer, all of which sit behind interfaces (ADR-0018, ADR-0020, ADR-0025) precisely so they can change.

**Primary seam — the bot WebSocket protocol (PROTOCOL.md).** This is the highest single seam that still exercises nearly the entire system: matchmaking/pairing, `python-chess` legality, the server-authoritative clock and flag detection, illegal-move forfeit, resign/draw, `ply`-idempotency, reconnect resume, and atomic finalization all live behind this one contract. Tests drive an **in-process fake protocol client** (a minimal thing that speaks the JSON wire format — not the real SDK, which is a separate repo per ADR-0021) and assert on the messages the server returns. Because the fake client is scripted, the hard, timing-sensitive edge cases can be driven **deterministically** (which a real browser/SDK cannot):

- Happy path: `hello → welcome → seek → seek_ack → game_start → your_turn/move loop → game_over`, bot-vs-bot and bot-vs-house-bot, to a real `checkmate`/`resignation` result with correct PGN and Elo change.
- Clock & flag: a side that never moves flags; result is `timeout` for the correct color; the clock runs from `your_turn` send (server-authoritative — a controllable clock source is the one internal seam this needs).
- Illegal / unparseable move at the current ply → immediate `game_over` with `termination: "illegal_move"` (forfeit); non-move junk → `INVALID_MESSAGE`, game continues, clock keeps running.
- Idempotency: duplicate `move` (same game+ply+uci) re-acks without re-applying; stale lower ply ignored and unpenalized; future ply → `INVALID_PLY`.
- Reconnect: a fresh handshake mid-game yields `welcome.active_game` with the correct resume payload; newest-wins closes the prior socket; a bot that flagged while away gets `game_over` instead.
- Draws: agreement via offer/accept; server auto-draw on stalemate / insufficient material / threefold / fifty-move; timeout-vs-insufficient-material → `draw`.
- Matchmaking rules: same-owner bots never paired; house bots exempt; seek TTL → `seek_ended: "expired"`; anti-rematch cooldown.
- Lifecycle/abort: start-grace expiry (`PAIRED → ABORTED`); mutual abandonment via missed heartbeat (`IN_PROGRESS → ABORTED`, no result, no rating change).

**One end-to-end smoke test.** A single happy-path test covering the actual demoable slice (ADR-0023): stubbed GitHub OAuth → create bot → a bot client connects and is matched against a house bot → plays a full 3+0 game to a result → assert the game appears on the spectator dashboard and the PGN lands in the bot's profile. This is a **smoke test that proves the wiring**, not where logic is exercised — all edge cases live at the primary WS seam above. Kept to one because full-stack E2E is slow and cannot force edge cases deterministically.

**Thin supporting suites** at the two other public contracts:
- **REST management API:** stubbed-OAuth login; bot CRUD; key shown-once then only-hash-stored; rotation invalidates the old key immediately; 5-bots-per-user cap enforced; read-only game-history / W-L endpoint returns finalized records.
- **Spectator SSE:** join yields the correct catch-up snapshot; subsequent moves arrive as live events in order; replay from move 1; auto-reconnect resumes cleanly.

**Modules under test (by seam, not by internal unit):** the bot WebSocket handler + game engine + matchmaker + clock + finalization (primary WS seam); the REST auth/bot/history surface; the SSE spectator surface; and the demoable slice (E2E smoke).

**Prior art:** none — this is a greenfield repo. This PRD establishes the seam convention: **assert at the public contract; keep the number of seams minimal (one primary + one E2E smoke + two thin supporting suites); do not test internals.** Later work should extend the existing suites rather than open new seams.

---

## Out of Scope

Explicitly **not** in v1 (from REQS and ADR-0023 "Deferred"):

- **No hosting/execution of user code.** Bots run on the user's own machine/cloud and connect outward to us. We provision no compute.
- **No human-vs-bot or human-move play.** Strictly bot-vs-bot; humans only manage settings and spectate.
- **No native legacy protocol on the server.** No raw UCI/XBoard accepted server-side. The client-side UCI bridge is the supported path.
- **No anti-cheat / code-originality verification.** We do not check whether a bot is secretly Stockfish.
- **No Bullet (1+0) and no RTT/latency compensation.** Blitz floor only (3+0, 5+0); a bot eats its own latency.
- **No multi-worker scale-out, Redis, or crash recovery** of in-progress games. Single process; worker-crash game loss is an accepted MVP risk. (The `MatchmakingQueue`/`PubSub` interfaces are in place so this can be added later without touching call sites.)
- **No tournaments / multi-game "matches."** Single Games only.
- **No Google/password auth** (GitHub OAuth only), **no non-Python SDKs**, **no Premium tier**.
- **No leaderboard UI** at MVP — the rating and history *data* exist and are queryable, but the ranked view is deferred.
- **No per-time-control ratings** — a single global Elo per Bot at MVP.
- **No direct challenges / challenge-by-name** — anonymous auto-pairing only.
- **No spectator chat, accounts, or lobby SSE** — spectating is anonymous; the lobby uses REST polling at MVP.

---

## Further Notes

### Open questions / assumptions to confirm at build time
These are tracked as still-open in QUESTIONS.md and are surfaced here rather than invented. They are **non-blocking** (tuning/build-time details) but should be resolved by whoever builds the affected slice:

- **D4 — starting position.** *Assumption:* standard starting position only at MVP; Chess960/custom deferred (consistent with ADR-0006). Confirm before building the game-init path.
- **F4 — spectator fan-out scale.** The concurrent-spectator limit and the Redis pub/sub fan-out design for multi-worker broadcast are unspecified. *Assumption:* single-process in-process fan-out is sufficient at MVP scale; the `PubSub` interface leaves room for the Redis design later.
- **K3 — hosting target.** Single VM vs container platform vs serverless is undecided. **Constraint to honor:** the bot transport is a *persistent* WebSocket, so a serverless model whose connection lifecycle conflicts with long-lived sockets is likely unsuitable. Resolve before choosing deployment.
- **K4 — target concurrency.** Target concurrent live games and concurrent bot connections at MVP are unset. Needed to validate the single-process assumption and to set the abuse rate-limit numbers concretely.
- **PGN retention & history-API shape** (J3/J4): PGNs are saved at MVP, but retention policy and the exact history-API response shape are build-time details.
- **House-bot count & strength** (ADR-0022 follow-up): how many house bots and at what rating spread — enough to guarantee a match and a lively lobby — is unspecified.
- **Numeric protocol defaults** (PROTOCOL §13): ping interval, liveness timeout, start-grace, and seek TTL are tunable; the values in this PRD are the current defaults, to be tuned with data.

### Traceability
Every implementation decision above traces to an ADR (`docs/adr/0001–0025`) or to PROTOCOL.md v1.0. The glossary and domain model in CONTEXT.md define the vocabulary used throughout. This PRD is the synthesis layer; when a decision needs its "why," read the linked ADR.
