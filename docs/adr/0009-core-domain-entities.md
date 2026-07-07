# ADR-0009: Core domain entities — User, Bot, Session, Game

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Rounds 1–2 repeatedly referenced User/Bot/Game/Session without ratifying them. ADR-0004 established that a bot's game identity must outlive a single socket. We now fix the core entities, their ownership, and their cardinalities. Answers QUESTIONS A1, A2, A3, A4; resolves E6.

## Decision

**Entities and relationships:**
- **User** — a human account. Owns bots; manages settings; spectates. Never plays moves (REQS).
- **Bot** — a **first-class, persistent entity** with its own identity, `name`, `description`, and (future) rating and history/stats. A **User owns many Bots** (1→N). Future, not modeled now: avatar, tags.
- **Session** — one continuous authenticated WebSocket connection for a Bot. A **Bot has many Sessions over time, but at most one *live* Session at a time.**
- **Game** — one bot-vs-bot contest with one Result (ADR-0008). Has two **seats** (White, Black), each bound to a Bot for the duration of the game.

**Naming (human-chess convention):**
- **"Game"** = the single contest (the MVP unit). We do **not** use "match" as a synonym.
- Reserved for the future: **"Match"** = a series of games between the same two bots; **"Tournament"** = a multi-bot bracket (the REQS tournament nice-to-have).

**Key invariants:**
- A Game seat is bound to a **Bot**, not to a Session. The live Session is the swappable transport that fills the seat; on drop, a new Session re-attaches to the same seat within the reconnect window (ADR-0004). "Disconnected" is a seat/session substate, **not** a Game state.
- One live Session per Bot ⟹ **a Bot is in at most one active Game at a time** (resolves E6 for MVP).

## Alternatives considered
- **Bot as just a token held by a User** (not first-class) — rejected; kills per-bot identity, history, and rating, which REQS wants (leaderboard/stats nice-to-haves).
- **Seat bound to a Session** (not a Bot) — rejected; makes reconnect impossible, contradicting ADR-0004.
- **"Match" as the single-contest term** — rejected; collides with the standard chess meaning and blocks the tournament naming ladder.

## Consequences
- Positive: clean ownership (User→Bot→Sessions), reconnect falls out naturally, per-bot stats/rating have a home, tournament vocabulary is preserved.
- Negative / costs: must enforce the single-live-Session invariant (collision handling — see A6) and separate credentials at the Bot level (→ auth, QUESTIONS G2).
- Follow-on questions opened:
  - A6: when a Bot opens a second WebSocket while one live Session exists — reject the new one, or replace the old? What token/handle proves session continuity for reconnect?
  - Matchmaking operates on a **MatchmakingTicket** (a Bot's request to play, carrying desired time control) that becomes a Game on pairing — ratify in the matchmaking ADR (Section E).
