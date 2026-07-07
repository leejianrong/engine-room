# ADR-0008: Result & termination-reason vocabulary; resign and draw-offer messages

- **Status:** accepted (recommendation — flag to revisit)
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
We must define how games end and how outcomes are recorded, and confirm which non-move signals bots may send. Answers QUESTIONS D3, D5; ties to ADR-0004 (disconnect) and ADR-0007 (illegal move).

## Decision
**Bots may send non-move control messages:** `resign` (unconditional) and `draw_offer` / `draw_accept` (an offer the opponent may accept on its move). Exact protocol timing is a follow-up (D6).

Outcomes are recorded as **two separate fields**:

**Result** (→ PGN tag): `WHITE_WINS` (`1-0`) · `BLACK_WINS` (`0-1`) · `DRAW` (`1/2-1/2`) · `ABORTED` (`*`).

**Termination reason:**
- Decisive: `CHECKMATE`, `TIMEOUT`, `RESIGNATION`, `ILLEGAL_MOVE`, `DISCONNECT_FORFEIT`
- Draw: `STALEMATE`, `INSUFFICIENT_MATERIAL`, `THREEFOLD_REPETITION`, `FIFTY_MOVE_RULE`, `AGREEMENT`
- No result: `ABORTED`

## Alternatives considered
- Single combined status field — rejected; separating *outcome* from *why* keeps stats/leaderboards clean and PGN mapping trivial.
- Moves-only protocol (no resign/draw) — rejected; real games need resignation and draw agreement, and it's cheap to support.

## Consequences
- Positive: clean mapping to PGN and to future Win/Loss/Elo stats; explicit reasons make spectator UX and debugging clear.
- Negative / costs: more states to implement and test; draw-offer flow adds protocol surface.
- Follow-on questions opened:
  - D6: draw-offer protocol — when may a bot offer, how is it surfaced to the opponent, does an offer expire?
  - D7: timeout-vs-insufficient-material should score as `DRAW`/`INSUFFICIENT_MATERIAL`, not a win — confirm we honor this.
  - D8: auto-draws (fivefold, 75-move) vs claimable draws (threefold, fifty-move) — does the server auto-draw or require a bot claim?
  - B7: is an `ILLEGAL_MOVE` an instant forfeit or is there one retry?
