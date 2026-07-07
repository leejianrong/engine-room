# ADR-0016: MVP defaults & fine-print decisions (batch)

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude
- **Amends:** ADR-0008 (draw handling), ADR-0012 (anti-rematch)

## Context
A batch of small, previously-deferred decisions cleared in one pass so no thread dangles. Each is individually cheap and tunable; recorded here for traceability. Resolves QUESTIONS A6, B7, E7, E8, F3, I7, D6, D7, D8, H5.

## Decisions

- **A6 — Session collision.** A new authenticated handshake for a Bot **replaces** any existing live Session (newest-wins); the old socket is closed. This is what makes reconnect over a half-dead socket work (ADR-0014). A leaked key can boot the live bot — accepted; rotation is the remedy.

- **B7 — Illegal/malformed move.** An illegal or unparseable *move* on the bot's turn = **instant forfeit** (`ILLEGAL_MOVE`, ADR-0008); no retry. Non-move junk messages are ignored/logged and do **not** stop the clock.

- **E7 — Start-grace.** PAIRED waits **~10s** for both bots to be ready; both are already connected (they queued over a live Session), so a no-show → **ABORTED** (no result, no rating change). Tunable.

- **E8 — Matchmaking numbers (MVP starting values, tune with data).**
  - Initial rating **1200**; K-factor **32** while provisional (<30 rated games), **16** after.
  - Rating window: start **±100**, widen **+100 every 10s**, **uncapped after 60s**.
  - Ticket max-wait TTL **120s** → CANCELED (requeue).
  - Min-pool: none — pair as soon as **≥2 eligible** tickets exist.
  - Rating scope: **single global Elo per Bot** at MVP (per-time-control deferred).

- **E5 refinement (amends ADR-0012) — soft anti-rematch.** Exclude a Bot's immediate previous opponent **only while another eligible opponent exists**; if none do, the exclusion lifts after the 60s widen. Replaces the hard cooldown, which would starve a 2-bot pool (they could never rematch).

- **F3 — Active-games list.** Shows both bots (name + rating), time control, move count, side-to-move. Updated by **REST poll** at MVP; a dedicated lobby SSE stream is a later upgrade.

- **I7 — Double-disconnect.** Both seats drop and neither reconnects within the window → **ABORTED** (no result), not a draw.

- **D6 — Draw-offer protocol.** A draw offer piggybacks on a move (or a control message on the bot's turn); it is surfaced in the opponent's next `your_turn`. It is valid until the opponent moves — **making a move implicitly declines**. Acceptance via `draw_accept` → `DRAW` / `AGREEMENT` (ADR-0008).

- **D7 — Timeout vs insufficient material.** If a bot flags but the opponent has insufficient mating material, the result is **DRAW / `INSUFFICIENT_MATERIAL`**, not a win (per standard rules; `python-chess` determines it).

- **D8 — Auto-draws, no claim (amends ADR-0008).** The server **automatically draws** on every standard drawing condition (stalemate, insufficient material, threefold repetition, fifty-move, fivefold, seventy-five-move). There is **no draw-claim protocol** at MVP — bots never "claim." Draw by **agreement** (D6) still exists.

- **H5 — Same-owner exclusion.** Matchmaking **never pairs two bots owned by the same User**, killing the trivial self-play rating-farming vector (ADR-0011). Cross-account collusion is out of scope for MVP.

## Consequences
- Positive: no dangling threads; consistent, tunable defaults; two genuine design bugs pre-empted (anti-rematch starvation, draw-claim complexity).
- Negative / costs: same-owner exclusion shrinks the effective pool for a User testing several of their own bots (they can't play each other) — accepted.
- Follow-on questions opened: none material. Numbers here are expected to be tuned once real traffic exists.
