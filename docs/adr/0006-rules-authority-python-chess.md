# ADR-0006: python-chess is the single rules authority

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
The server is the source of truth for board legality and game state; we will not reimplement chess rules. Answers QUESTIONS D1, D2; enables B3 (ADR-0007) and PGN export (J3).

## Decision
The backend uses **`python-chess`** as the authoritative engine for: move legality, check/checkmate/stalemate detection, threefold repetition, fifty-move rule, insufficient material, FEN (state) representation, PGN export, and UCI↔SAN conversion. The server validates every bot move against this library before applying it; the library's board is the single source of truth.

## Alternatives considered
- Hand-rolled rules engine — rejected; reimplementing chess rules is a well-known bug farm and time sink for zero differentiation.
- Shelling out to a UCI engine (e.g. Stockfish) for legality — overkill and slow; we need a rules/board model, not an evaluator.

## Consequences
- Positive: correct, battle-tested rules for free; directly provides UCI/SAN conversion (ADR-0007) and PGN export (J3); reinforces the Python/FastAPI choice (ADR-0005).
- Negative / costs: standard chess only unless configured otherwise; Chess960/variants inherit whatever the library supports (fine, out of MVP scope).
- Follow-on questions opened: auto vs claimable draws (fivefold/75-move are mandatory; threefold/fifty are claimable) — see new D8; timeout-vs-insufficient-material draw rule — see new D7.
