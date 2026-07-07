# ADR-0007: UCI coordinate notation as the single move wire format

- **Status:** accepted (recommendation — flag to revisit)
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Bots and server exchange moves over WebSocket (ADR-0002). We must pick the on-the-wire move encoding. Answers QUESTIONS B3; also touches B4/B5 (state format). Rules engine is `python-chess` (ADR-0006).

## Decision
Moves on the wire use **UCI long-algebraic coordinate notation** (`e2e4`, `e7e8q` for promotion, `e1g1`/`e1c1` for castling) — a single canonical wire format. The server converts to **SAN** for all human-facing surfaces (spectator move list, PGN export) via `python-chess`. We do **not** accept SAN on the wire at MVP. Game state on the wire is represented as **FEN** plus the last move.

## Alternatives considered
- **SAN on the wire** — human-readable but requires board context + disambiguation to emit/parse, with many valid stylings → larger validation surface and more spurious rejections. Readability is a presentation concern, solved server-side.
- **Accept both UCI and SAN** — a "flexibility tax": doubles parsing/validation surface and creates a canonical-format ambiguity for near-zero benefit, since any engine emits UCI trivially. Rejected for MVP; accepting SAN as input later is a small additive change if demanded.

## Consequences
- Positive: trivial and unambiguous for bots to emit/parse (it's what UCI engines already speak); minimal validation surface; SAN readability retained in the UI for free via `python-chess`.
- Negative / costs: raw wire logs aren't human-friendly (mitigated by server-side SAN rendering).
- Follow-on questions opened: does `your_turn` carry full FEN every turn, or move list + deltas (B5)? Illegal/malformed move handling — instant forfeit vs one retry (B7, ties to ADR-0008 `ILLEGAL_MOVE`).
