# Bot ↔ Server Wire Protocol — v1.0 (draft)

The contract between a bot client (e.g. the `chessroom` Python SDK) and the server.
This is a **public, versioned contract**: the SDK and server both conform to it, sharing
the spec, not code (ADR-0021). Human/management APIs (auth, bot CRUD, spectating) are **not**
covered here — they are REST/SSE; this document covers only the **bot WebSocket**.

Grounded in: ADR-0002 (WebSocket), ADR-0003 (clock), ADR-0007 (UCI/FEN), ADR-0008
(results/draws), ADR-0010 (lifecycle), ADR-0014 (auth/handshake), ADR-0016 (fine print),
ADR-0021 (versioning), ADR-0025 (seek-over-WS, clock-is-arbiter). Resolves QUESTIONS B5, C8, I4.

---

## 1. Transport & framing
- **WebSocket**, endpoint `wss://<host>/api/bot/v1` (major version in the path).
- Messages are **UTF-8 JSON text frames**, one JSON object per frame.
- Every message has a string **`type`** field.
- Client→server messages that need correlation carry a client-generated **`id`** (string); the matching server ack echoes it.
- **Units:** durations are integer **milliseconds** unless a field name says `_seconds`. Colors are `"white"` / `"black"`. Moves are **lowercase UCI** (`"e2e4"`, `"e7e8q"`, castling as the king move `"e1g1"`).

## 2. Versioning (ADR-0021)
- The URL path pins the **major** version (`/v1`). The `hello`/`welcome` handshake exchanges a full **semver** `protocol_version` (e.g. `"1.0"`).
- The server advertises the range it supports. On an unsupported version the server replies `error {code: "VERSION_UNSUPPORTED"}` and closes.

## 3. Authentication (ADR-0014)
- The bot's **API key** is sent in the `Authorization: Bearer <key>` **header on the WebSocket upgrade request** — never in the query string, never per-message.
- One live session per bot; a new authenticated connection **replaces** any prior live one (newest-wins, ADR-0016 A6) — the superseded socket receives `error {code:"SESSION_REPLACED"}` and is closed. Key **rotation** likewise terminates the live session (ADR-0014).
- Implemented in V2: the key is `crbk_<random>`, stored server-side only as `HMAC-SHA256(pepper, key)` and shown once at generation/rotation (ADR-0014).

---

## 4. Connection lifecycle

```
open WS (Authorization: Bearer <key>)
  client → hello
  server → welcome        (may include active_game on reconnect)
  [ if bot has an in-progress game, resume it; else it may seek ]
```

### `hello` (client → server)
```json
{ "type": "hello", "protocol_version": "1.0", "sdk": "chessroom-py/0.1.0" }
```

### `welcome` (server → client)
```json
{
  "type": "welcome",
  "protocol_version": "1.0",
  "session_id": "sess_9f...",
  "bot": { "id": "bot_123", "name": "my-first-bot", "rating": 1200 },
  "active_game": null
}
```
`active_game` is `null` normally. On **reconnect** it carries the full resume payload (see §8) so the bot can continue an in-progress game.

---

## 5. Matchmaking (seek-over-WebSocket, ADR-0025; resolves C7)

### `seek` (client → server)
```json
{ "type": "seek", "id": "c1",
  "time_control": { "base_seconds": 180, "increment_seconds": 0 } }
```
- `time_control` selects the pool (3+0 → `{180,0}`, 5+0 → `{300,0}`). The bot chooses its time control here (C7).

### `seek_ack` (server → client)
```json
{ "type": "seek_ack", "id": "c1", "seek_id": "seek_77", "status": "queued" }
```

### `seek_cancel` (client → server) / `seek_ended` (server → client)
```json
{ "type": "seek_cancel", "seek_id": "seek_77" }
{ "type": "seek_ended", "seek_id": "seek_77", "reason": "cancelled" }   // or "expired" (TTL, ADR-0016 E8)
```

### `game_start` (server → client)
```json
{
  "type": "game_start",
  "game_id": "game_abc",
  "your_color": "white",
  "opponent": { "id": "bot_999", "name": "house-random", "rating": 1200 },
  "time_control": { "base_seconds": 180, "increment_seconds": 0 },
  "initial_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "clocks": { "white_ms": 180000, "black_ms": 180000 },
  "start_grace_ms": 10000
}
```
On `game_start` the game is `PAIRED` (ADR-0010); clocks are **not yet running**. White receives its first `your_turn` when the game moves to `IN_PROGRESS` (within `start_grace_ms`, ADR-0016 E7).

---

## 6. In-game loop (the core exchange)

### `your_turn` (server → client)
```json
{
  "type": "your_turn",
  "game_id": "game_abc",
  "ply": 0,
  "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "last_move": null,
  "clocks": { "white_ms": 180000, "black_ms": 180000 },
  "your_color": "white",
  "opponent_draw_offer": false
}
```
- **`fen` is sent in full every turn** (resolves **B5**): stateless for the bot, ~70 bytes, no client board-sync bugs. Deltas were rejected as premature optimization — a `python-chess` bot reconstructs the board from FEN trivially.
- `last_move` is the opponent's move (`{ "uci": "...", "san": "..." }`) or `null` on the first move.
- **`ply`** is the half-move index the bot must now play at (0 = first White move). It is the anchor for ordering and idempotency (§9).
- **Clock semantics (resolves C8):** `clocks` are the remaining ms for each side **at the instant the server sent this `your_turn`**. Per ADR-0003 the side-to-move's clock starts running at that send instant and stops when the server receives the move — the bot eats its own network latency. `increment_seconds` (0 at MVP) is credited to the mover **after** their move is applied. (The server's internal monotonic time source is an implementation detail, not part of the wire contract.)

### `move` (client → server)
```json
{ "type": "move", "id": "c2", "game_id": "game_abc", "ply": 0,
  "uci": "e2e4", "offer_draw": false }
```
- **`ply` MUST equal** the `ply` from the `your_turn` the bot is answering (enables idempotency + ordering, §9).
- `offer_draw: true` piggybacks a draw offer on the move (ADR-0016 D6).

### `move_ack` (server → client)
```json
{ "type": "move_ack", "id": "c2", "game_id": "game_abc", "ply": 0, "accepted": true }
```
Confirms receipt/application. If the client gets no `move_ack` (network blip), it resends the **same** `move` (same `game_id`+`ply`+`uci`); the server handles it idempotently (§9).

- An **illegal or unparseable move at the current ply** ends the game immediately: server → `game_over` with `termination: "illegal_move"` (forfeit, ADR-0016 B7).
- **Non-move junk** (unknown `type`, malformed JSON) → `error {code:"INVALID_MESSAGE"}`; it is ignored and **the clock keeps running** (ADR-0016).

---

## 7. Control messages

### Resign (client → server)
```json
{ "type": "resign", "game_id": "game_abc" }
```

### Draw (ADR-0008 / ADR-0016 D6, D8)
- **Offer:** set `offer_draw: true` on a `move`, or send a standalone offer on your turn:
  ```json
  { "type": "draw_offer", "game_id": "game_abc" }
  ```
- **Accept:** when `your_turn.opponent_draw_offer` is `true`, reply with:
  ```json
  { "type": "draw_accept", "game_id": "game_abc" }
  ```
- **Decline** is implicit: making a normal `move` declines the standing offer.
- Note: standard draws (stalemate, insufficient material, threefold, fifty-move, fivefold, 75-move) are applied **automatically by the server** — bots never claim them (ADR-0016 D8). `draw_offer`/`draw_accept` cover **agreement** only.

---

## 8. Game end & reconnect payload

### `game_over` (server → client)
```json
{
  "type": "game_over",
  "game_id": "game_abc",
  "result": "white_wins",
  "termination": "checkmate",
  "final_fen": "....",
  "pgn": "[Event ...]\n1. e4 ...",
  "rating": { "before": 1200, "after": 1208 }
}
```
- `result` ∈ `white_wins | black_wins | draw | aborted`; `termination` ∈ the ADR-0008 vocabulary (`checkmate, timeout, resignation, illegal_move, disconnect_forfeit, stalemate, insufficient_material, threefold_repetition, fifty_move, agreement, aborted`).
- `rating` is this bot's Elo change (absent for `aborted`, which does not affect rating — ADR-0011/0016).

### Reconnect (I6, ADR-0014/0025) — *implemented in V4*
On reconnect the bot simply re-opens the WebSocket with the same key and sends `hello`. The `welcome.active_game` is populated:
```json
{ "type": "welcome", "protocol_version": "1.0", "session_id": "sess_new",
  "bot": { "id": "bot_123", "name": "my-first-bot", "rating": 1200 },
  "active_game": {
    "game_id": "game_abc", "your_color": "white",
    "fen": "....", "ply": 4, "last_move": { "uci": "e7e5", "san": "e5" },
    "clocks": { "white_ms": 171200, "black_ms": 176500 },
    "opponent_draw_offer": false,
    "to_move": "white"
  }
}
```
If it is the bot's turn, the server also (re)sends `your_turn`. Because the **clock is the sole arbiter** (ADR-0025), no separate reconnect window is enforced — the bot simply resumes; if it had flagged while away, it instead receives `game_over`.

---

## 9. Move idempotency & ordering (resolves I4) — *implemented in V4*

The `ply` counter makes the exchange safe against resends and reconnects:

- The server tracks the **expected ply** (the next half-move to be played).
- A `move` is **applied only if `move.ply == expected_ply`**. On success, `expected_ply` increments and a `move_ack` is sent.
- **Duplicate** (`move.ply < expected_ply` **and** `uci` matches what was already applied at that ply): the server **re-sends the ack/resulting state and does NOT re-apply** — safe for blind resends after a blip.
- **Stale/conflicting** (`move.ply < expected_ply` and `uci` differs): ignored as a late duplicate; **not** penalized (it is not a fresh illegal move).
- **From the future** (`move.ply > expected_ply`): `error {code:"INVALID_PLY"}`, ignored.
- Only a move **at the current ply that is illegal** triggers forfeit (§6).

This lets an SDK safely "send, and resend on missing ack / after reconnect" without ever double-applying or self-forfeiting.

## 10. Heartbeat / liveness (ADR-0025) — *implemented in V4*
- The server sends `{"type":"ping","t":<ms>}` on an interval (default **10s**, `ER_HB_PING_INTERVAL_SECONDS`); the client replies `{"type":"pong","t":<same>}`.
- A peer that misses the liveness timeout (default **~30s** / 3 missed, `ER_HB_LIVENESS_TIMEOUT_SECONDS`) is treated as disconnected — its socket is closed (turning a half-dead socket into a real disconnect).
- Liveness is used **only** to detect **mutual abandonment** (both seats gone → game `ABORTED`, ADR-0025/I7). A single disconnected bot is **not** forfeited by heartbeat — only by its game clock.

## 11. Errors
`{ "type": "error", "code": "...", "message": "...", "fatal": false }`

| code | meaning | fatal (server closes) |
|------|---------|-----------------------|
| `UNAUTHORIZED` | bad/rotated/missing key | yes |
| `SESSION_REPLACED` | a newer authenticated connection (or key rotation) superseded this session — newest-wins, ADR-0016 A6 (WS close 4001) | yes |
| `VERSION_UNSUPPORTED` | protocol version out of range | yes |
| `RATE_LIMITED` | seek/message rate exceeded (ADR-0019/0025) | no |
| `INVALID_MESSAGE` | unknown type / malformed JSON | no |
| `NOT_YOUR_TURN` | move sent when not to move | no |
| `INVALID_PLY` | move ply ≠ expected (§9) | no |
| `NO_ACTIVE_GAME` | game-scoped message with no such game | no |

---

## 12. Example transcript (happy path, 3+0)
```
C→ hello {protocol_version:"1.0"}
S→ welcome {bot:{...}, active_game:null}
C→ seek {id:"c1", time_control:{base_seconds:180, increment_seconds:0}}
S→ seek_ack {id:"c1", seek_id:"seek_77", status:"queued"}
S→ game_start {game_id:"g1", your_color:"white", opponent:{name:"house-random"}, initial_fen:"...", clocks:{180000,180000}, start_grace_ms:10000}
S→ your_turn {game_id:"g1", ply:0, fen:"...", last_move:null, clocks:{180000,180000}}
C→ move {id:"c2", game_id:"g1", ply:0, uci:"e2e4"}
S→ move_ack {id:"c2", ply:0, accepted:true}
   ... (opponent moves; server sends your_turn ply:2, etc.) ...
S→ game_over {result:"white_wins", termination:"checkmate", pgn:"...", rating:{before:1200, after:1208}}
```

---

## 13. Open items / roadmap
- Exact numeric defaults (ping interval, liveness timeout, start-grace, seek TTL) are tunable — see QUESTIONS E8/C8-adjacent.
- v1.x may add: SAN as an accepted **input** (still UCI-canonical, ADR-0007), per-time-control ratings, spectator-side protocol doc, and increment time controls (the `{base,increment}` model already supports it; increment path is dormant at MVP, ADR-0025 #6).
- The authoritative machine-readable schema (JSON Schema) is a future artifact derived from this doc (ADR-0021 follow-up).
