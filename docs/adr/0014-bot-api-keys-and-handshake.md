# ADR-0014: Bot credentials & Session authentication (WebSocket handshake)

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Bots authenticate to open a Session and hold a MatchmakingTicket (ADR-0009, ADR-0012). This ADR fixes the bot credential and *is* the answer to the WebSocket handshake question. Answers QUESTIONS G2, G3, G4, B6; resolves I6; informs A6.

## Decision
- **One rotatable API key per Bot** (not per User) — consistent with Bot being first-class (ADR-0009).
- **Stored hashed** (salted), never in plaintext. The plaintext key is shown **once** at generation/rotation and is unrecoverable thereafter — only rotatable.
- **Prefixed, high-entropy token** (e.g. `crbk_<random>`) so it is identifiable/greppable in leak scanning.
- **Rotation invalidates the old key instantly** (no grace period). Any live Session authenticated with the old key is terminated on rotation.
- **Presentation:** the key is sent in the `Authorization: Bearer <key>` header on the **WebSocket HTTP upgrade request** (bots are non-browser clients, so custom headers are fine). **Not** in the query string (log-leak risk).
- **Handshake = Session auth:** the server validates the key → identifies the Bot → establishes one authenticated Session. Enforces ≤1 live Session per Bot (ADR-0009).
- **Reconnect (I6):** to resume, the bot reconnects with the **same API key**; the server finds that Bot's active IN_PROGRESS Game/seat and re-binds the seat to the new Session. The key alone proves identity; the bot may also reference `game_id`.

## Alternatives considered
- **Per-User token** — rejected; breaks per-bot identity and per-bot revocation.
- **Static, non-rotatable key** — rejected; no leak recovery.
- **Storing keys in plaintext / retrievable** — rejected; treat like a password (hash + one-time reveal).
- **Key in query param or WS subprotocol** — rejected (logs leakage / awkwardness); header is clean for non-browser clients.

## Consequences
- Positive: clean per-bot revocation, leak recovery via rotation, minimal secret handling, one credential covers connect + reconnect.
- Negative / costs: a bearer key is impersonation-capable if leaked (mitigated by hashing, one-time reveal, instant rotation). Instant rotation disconnects a running bot using the old key — intended.
- Follow-on questions opened:
  - A6 (still to ratify): when a *second* valid handshake arrives while a live Session exists — **newest-wins/replace** (cleanly implements reconnect over a half-dead socket) vs **reject-new**. Lean: newest-wins.
  - B6 residual: does the handshake also carry a protocol **version**? (minor; likely a header field.)

## Update — implemented in V2 (2026-07-08)

- **Hashing (D-k, refines "salted"):** keys are stored as **`HMAC-SHA256(server pepper, key)`**, an indexed unique `key_hash`, not a per-row salted+slow hash. A per-row salt is incompatible with the O(1) key→bot lookup the WS handshake needs, and a 256-bit random token has no dictionary to attack, so a fast **keyed** hash is the right tool. The pepper (`ER_API_KEY_PEPPER`) preserves the ADR's intent — a DB leak alone yields no usable credentials. Token format: `crbk_<43 base62>` (~256 bits); a non-secret `key_prefix` is stored for display.
- **A6 ratified → newest-wins.** A second authenticated handshake replaces the prior live Session (in-memory `SessionRegistry`, single process); the old socket is closed with a `SESSION_REPLACED` error (WS close 4001). Key **rotation** likewise evicts + closes the live session immediately. *Mid-game seat reconnect/resume* (`welcome.active_game`) remains V4 — V2 proves session replacement only.
- **B6:** the protocol version is exchanged in the `hello`/`welcome` body (PROTOCOL.md §2), not a header.
