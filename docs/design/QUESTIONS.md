# QUESTIONS

The full grilling backlog. Questions are dumped up front and appended as they surface.
Status: 🔴 open · 🟡 partially answered · 🟢 answered (see CONTEXT.md / relevant ADR)

Legend for leverage: ⭐️ = high-leverage (drives many downstream decisions).

---

## A. Domain & ubiquitous language
- 🟢 A1. → **"Game"** for the single contest; "Match"/"Tournament" reserved for future multi-game constructs (ADR-0009).
- 🟢 A2. → **Bot is first-class & persistent** (identity, name, description, future rating/stats); **1 User → N Bots** (ADR-0009).
- 🟢 A3. → User = human account (owns bots, spectates, never plays); Bot = the automated player entity (ADR-0009).
- 🟢 A4. → **Session is first-class**; 1 Bot → N Sessions over time, **≤1 live at a time** (ADR-0009). Enables reconnect + per-bot stats.
- 🟢 A5. → Ratified state machine: **QUEUED→PAIRED→IN_PROGRESS→FINISHED|ABORTED** (ADR-0010).
- 🟢 A6. → **Newest-wins**: a new authenticated handshake replaces the old Session (closes old socket); reconnect = same key (ADR-0016).

## B. Bot ↔ server protocol & transport ⭐️
- 🟢 B1. ⭐️ Transport → **persistent WebSocket** (ADR-0002).
- 🟢 B2. → Bot holds a persistent connection; **server pushes** `your_turn` events (ADR-0002).
- 🟢 B3. → **UCI coordinate notation**, single canonical wire format; SAN is display-only (ADR-0007).
- 🟢 B4. → **FEN** for state (+ last move) on the wire (ADR-0007).
- 🟢 B5. → **Full FEN every `your_turn`** (+ last move + clocks); stateless for the bot, deltas rejected (PROTOCOL.md §6).
- 🟢 B6. → Handshake authenticates via the bot API key (ADR-0014) **and carries a protocol version** for SDK/server compatibility (ADR-0021).
- 🟢 B7. → **Instant forfeit** (`ILLEGAL_MOVE`), no retry; non-move junk ignored, clock keeps running (ADR-0016).

## C. Clock & time control ⭐️
- 🟢 C1. ⭐️ → **Server-authoritative**; clock runs from server-send of `your_turn` to server-receive of the move (ADR-0003). _Sub-q: exact start point (send vs socket-flush) + monotonic source — see C8._
- 🟢 C2. → **Bot eats its own latency**; no RTT compensation at MVP (ADR-0003).
- 🟢 C3. → **Blitz only (3+0, 5+0)**, modeled as `{base, increment}` (ADR-0001).
- 🟢 C4. → Answered by ADR-0001: don't start at Bullet; Blitz is the safe floor on uncontrolled networks.
- 🟢 C5. → **No** separate per-move connection grace at MVP (rejected in ADR-0003 as gameable).
- 🟢 C6. → **Auto-detected server-side**, instantly; not opponent-claimed (ADR-0003).
- 🟢 C7. → **Per-seek selectable**: the bot specifies its time control in the `seek` message it sends over the WebSocket (ADR-0025).
- 🟡 C8. → **Protocol-level resolved**: clocks carried as remaining ms, running from `your_turn` send instant; increment credited post-move (PROTOCOL.md §6). Server-internal monotonic source is an impl detail (non-blocking).

## D. Chess rules & authority ⭐️
- 🟢 D1. ⭐️ → **Yes**, server is single source of truth; `python-chess` board is authoritative (ADR-0006).
- 🟢 D2. → **`python-chess`** (ADR-0006).
- 🟢 D3. → **Yes** — bots may `resign` and `draw_offer`/`draw_accept` (ADR-0008).
- 🔴 D4. Starting position always standard, or Chess960/custom later? (standard-only at MVP per ADR-0006; confirm)
- 🟢 D5. → Two fields: **Result** {WHITE_WINS/BLACK_WINS/DRAW/ABORTED} + **termination reason** enum (ADR-0008).
- 🟢 D6. → Offer piggybacks on a move; surfaced in opponent's next `your_turn`; valid until opponent moves (move = implicit decline) (ADR-0016).
- 🟢 D7. → **Yes**, honor it — timeout vs insufficient material = DRAW (ADR-0016).
- 🟢 D8. → **Server auto-draws** on all standard conditions; **no claim protocol** at MVP (ADR-0016).

## E. Matchmaking ⭐️
- 🟢 E1. ⭐️ → **Elo-based pairing** (widening-window); ratings are MVP, per-Bot (ADR-0011).
- 🟢 E2. → **Yes, pools segmented by time control**; single global rating per Bot at MVP (ADR-0012).
- 🟢 E3. → **Anonymous auto-pairing only** at MVP; no challenge-by-name (ADR-0012).
- 🟢 E4. → Ticket **max-wait TTL → give up (CANCELED)** + min-pool guard; numbers in E8 (ADR-0012).
- 🟢 E5. → **Anti-rematch cooldown** prevents back-to-back repairs; length in E8 (ADR-0012).
- 🟢 E8. → MVP defaults set: rating 1200, K 32→16@30 games, window ±100 +100/10s uncapped@60s, TTL 120s, pair@≥2, **soft** anti-rematch, single global rating (ADR-0016). Tune with data.
- 🟢 E6. → **No** — one live Session per Bot ⟹ one active Game per Bot at MVP (ADR-0009).
- 🟢 E7. → **~10s** start-grace; no-show → ABORTED (no result). Tunable (ADR-0016).

## F. Spectating ⭐️
- 🟢 F1. ⭐️ → **SSE** (read-only, auto-reconnect); separate from the bot WebSocket, clean trust boundary (ADR-0015).
- 🟢 F2. → **No broadcast delay** — bots already hold the authoritative position, so there's nothing to leak; anti-relay purpose N/A bot-vs-bot (ADR-0015).
- 🟢 F3. → Shows both bots (name+rating), time control, move count, side-to-move; **REST poll** at MVP (lobby SSE later) (ADR-0016).
- 🔴 F4. Concurrent-spectator fan-out scale + the Redis pub/sub design for multi-worker broadcast. (opened by ADR-0015; ties K2)
- 🟢 F5. → **Yes** — catch-up snapshot (FEN + clocks + move list + players/ratings) on join, then live SSE; move history enables **replay from move 1** (ADR-0015).
- 🟢 F6. → **Anonymous** (no login) for the discovery funnel (ADR-0015).

## G. Auth & identity
- 🟢 G1. → **GitHub OAuth** via **FastAPI-Users**, modular for Google/password later (ADR-0013).
- 🟢 G2. → **One rotatable API key per Bot**, stored hashed, prefixed token (ADR-0014).
- 🟢 G3. → **Yes** — rotation regenerates and **instantly invalidates** the old key (ADR-0014).
- 🟢 G4. → **Per-connection**: `Authorization: Bearer` header on the WebSocket upgrade (not per-message, not query param) (ADR-0014).

## H. Abuse prevention (REQS open question)
- 🟢 H1. ⭐️ → **5 bots/User** (Premium raises it later); one bot = one game ⟹ ≤5 concurrent games/user (ADR-0019).
- 🟢 H2. → **Rate-limit connect/queue/inbound-messages**; excess messages → disconnect (ADR-0019).
- 🟢 H3. → Track per-bot disconnect/abort/illegal rates; **soft escalating temp-cooldown** for repeat offenders (ADR-0019).
- 🟢 H4. → **Valid GitHub account** (OAuth) is the human gate; no captcha; account-age as a later signal (ADR-0019).
- 🟢 H5. → **Same-owner exclusion**: matchmaking never pairs two bots of the same User (ADR-0016). Cross-account collusion out of scope for MVP.

## I. Reconnection & failure handling ⭐️
- 🟢 I1. ⭐️ → **Reconnect and resume** within a window; else forfeit (ADR-0004).
- 🟢 I2. → Yes, a reconnect window; the **clock keeps running** during the drop (ADR-0004).
- 🟢 I5. → **Moot** — no separate reconnect window; the **game clock is the sole arbiter** (ADR-0025). Heartbeat exists only to detect mutual abandonment → ABORT.
- 🟢 I6. → Reconnect with the **same bot API key**; server re-binds the Bot's active seat (optionally referencing `game_id`) (ADR-0014).
- 🟢 I7. → **ABORTED** (no result), not a draw (ADR-0016).
- 🟡 I3. → **Accepted MVP risk**: a worker crash loses its in-progress games; not recoverable until live-state-in-Redis is added later (ADR-0018, ADR-0020). Recovery mechanism = deferred.
- 🟢 I4. → **`ply`-anchored idempotency**: a move applies only at the expected ply; matching-uci resends re-ack without re-applying; stale/conflicting are ignored, never penalized (PROTOCOL.md §9).

## J. Persistence & data
- 🟢 J1. → **In-memory in the game's worker** at MVP; not persisted per-move (ADR-0018).
- 🟢 J2. → **Postgres** for records (written at finalization); **Redis = pub/sub only** at MVP, not live-state (ADR-0018).
- 🟢 J3. → **Yes, PGNs at MVP** — near-free given Elo persistence + `python-chess` (ADR-0018). Retention TBD (build-time).
- 🟢 J4. → **Yes** — read-only game history API for bot profiles/W-L (ADR-0018).

## K. Scale, deployment & stack ⭐️
- 🟢 K1. ⭐️ → **Python + FastAPI** backend, **Postgres** records, **TypeScript** frontend (ADR-0005).
- 🟢 N1. → **Svelte** (flip to React on preference) (ADR-0017).
- 🟢 K2. → **Single game-process at MVP**; scale via **Redis-bridged edge/home worker** (global Redis queues, game→worker registry, bot bus == spectator bus) (ADR-0020).
- 🟢 K3. → **Fly.io** (a single always-on machine — the MVP is one in-memory game-worker, ADR-0018/0020, so no autoscale / no scale-to-zero) + **Neon** managed Postgres; frontend on a separate origin via CORS (Bearer-JWT auth). **Serverless was rejected** for the MVP precisely because its autoscaling + scale-to-zero + request lifecycle conflict with persistent WebSockets and single-process in-memory state (ADR-0026). Deploy is CI-gated (`deploy.yml`); see `docs/DEPLOY.md`.
- 🔴 K4. Target concurrent live games and concurrent bot connections at MVP? *(Doesn't change the host — smallest Fly VM covers the MVP — but pin a number before a real launch to size up. ADR-0026.)*

## L. Adapter / developer experience (REQS open question)
- 🟢 L1. → **Yes, official Python SDK** at launch (own repo, decoupled, protocol-spec-only dependency) (ADR-0021).
- 🟢 L2. → **Yes, client-side UCI bridge** via `python-chess` `chess.engine`; never server-side (ADR-0021).
- 🟢 L3. → GitHub → create bot (key shown once) → clone quickstart → run; **house bots** guarantee an instant first game (ADR-0022).

## M. MVP scope & success
- 🟢 M1. → Signup → bot+key → clone quickstart → run → matched vs house bot → full 3+0 Blitz game watched live, PGN saved (ADR-0023).
- 🟢 M2. → v1 in/out line fixed (ADR-0023); deferred: Bullet, multi-worker scale, tournaments, Google/password, non-Python SDKs, Premium, leaderboard UI, per-TC ratings.
- 🟢 M3. → Primary user = **AI/CS student writing first bot**; win = zero→live game in minutes, no plumbing ⟹ SDK/quickstart is the hero path (ADR-0023).

---

## Follow-ups raised during grilling
_(appended live as answers open new questions)_

- Round 1 (real-time spine, ADR-0001..0004) opened: **C7, C8** (time-control config + clock precision), **I5, I6** (reconnect window length + reconnect auth). Filed inline in their sections above.
- Round 2 (rules/wire/stack/outcomes, ADR-0005..0008) opened: **D6, D7, D8** (draw mechanics + edge cases), **N1** (Svelte vs React), and sharpened **B5, B7, D4**. Filed inline above.
- Round 3 (domain model, ADR-0009..0010) opened: **A6** (session collision), **E7** (start-grace window), **I7** (double-disconnect abort). Resolved **E6**. Filed inline above.
- Round 4 (matchmaking, ADR-0011..0012) opened: **E8** (all matchmaking numbers + per-TC ratings), **H5** (rating-farming via self-owned bots). Resolved **E1–E5**. Amended ADR-0009 (rating → MVP). Filed inline above.
- Round 5 (auth, ADR-0013..0014) opened: protocol-version residual on B6, sharpened **A6** (newest-wins lean). Resolved **G1–G4, I6**. Filed inline above.
- Round 6 (spectating, ADR-0015) opened: **F3** (lobby list contents + update), **F4** (fan-out scale + Redis pub/sub). Resolved **F1, F2, F5, F6**. Corrected earlier "broadcast delay" lean → not needed bot-vs-bot. Filed inline above.
- Round 7 (batch + persistence, ADR-0016..0018) resolved **A6, B7, E7, E8, F3, I7, D6, D7, D8, H5, N1, J1–J4**. Amended ADR-0008 (auto-draws) & ADR-0012 (soft anti-rematch). No new material follow-ups.
- Round 8 (abuse + topology, ADR-0019..0020) resolved **H1–H4, K2**. Opened (non-blocking): worker failover/rebalance, matchmaker-as-coordinator-vs-leader. The REQS "500 dummy bots" open question is now answered (caps + same-owner exclusion + rate limits).
- Round 9 (adapter/DX, ADR-0021..0022) resolved **L1, L2, L3, B6**. Answered the REQS "official wrapper?" open question (yes: Python SDK + client-side UCI bridge). Opened (non-blocking): protocol-spec location/versioning, house-bot count/strength. **All three REQS open questions now closed.**
- Round 10 (MVP scope, ADR-0023) resolved **M1, M2, M3**. Demoable slice + v1 boundary + primary user (AI/CS student) fixed. **All 13 backlog sections settled.**
- Round 11 (bot tooling, ADR-0024) resolved tooling: **uv + pyproject.toml**, container as optional path. Amends ADR-0021/0022.
- **A2 consistency pass (ADR-0025)** — fixed 2 contradictions (house-bot same-owner; Redis-in-MVP), simplified disconnect (clock is sole arbiter), nailed queue-over-WS, + atomic finalization / increment-dormant / spectator cap. Resolved **C7, I5**. Amends ADR-0004/0016/0018/0019/0022.
- **Protocol spec drafted (PROTOCOL.md)** — the bot↔server WebSocket wire contract. Resolved **B5** (full FEN/turn), **I4** (ply-anchored idempotency), and **C8** at the protocol level. Defines hello/seek/your_turn/move/game_over/heartbeat + reconnect + error codes.
