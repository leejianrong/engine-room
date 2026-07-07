# ADR-0010: Game lifecycle state machine

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
We need one explicit, authoritative lifecycle for a Game so clocks, matchmaking, spectating, and persistence all agree on state. Answers QUESTIONS A5. Builds on ADR-0009 (entities), ADR-0004 (disconnect), ADR-0008 (results).

## Decision

Four Game states — two live, two terminal:

- **QUEUED** — the pre-pairing state. Modeled on a **MatchmakingTicket** (a Bot's request to play). No opponent yet; no clocks. (A ticket that is withdrawn before pairing is **CANCELED** — a ticket outcome, not a Game.)
- **PAIRED** — two bots matched; the Game exists with both seats bound (ADR-0009). Initial position set; **clocks not yet running.** Awaiting both bots ready/connected within a start-grace window.
- **IN_PROGRESS** — moves exchanged, clocks running (bot eats latency, ADR-0003). A seat may be transiently disconnected here (reconnect window, ADR-0004) **without leaving this state** — disconnect is a seat substate, not a Game state.
- **FINISHED** — terminal. Carries a Result + termination reason (ADR-0008).
- **ABORTED** — terminal. **No result.** Used when no fair result exists.

### Transitions

```
             (bot queues → ticket)
                      │
                      ▼
   ┌──────────┐  matchmaker    ┌──────────┐  both ready   ┌──────────────┐
   │  QUEUED  │ ─pairs 2 bots─▶ │  PAIRED  │ ────────────▶ │ IN_PROGRESS  │
   └──────────┘                └──────────┘               └──────────────┘
        │                           │                        │        │
   (withdraw)              (start-grace expires:      (game ends,   (unrecoverable:
        │                   a bot never readies)       ADR-0008)    both drop / server fault)
        ▼                           ▼                        ▼        ▼
  [ticket CANCELED]            ┌──────────┐          ┌──────────┐  ┌──────────┐
   (not a Game)                │ ABORTED  │          │ FINISHED │  │ ABORTED  │
                               └──────────┘          └──────────┘  └──────────┘
```

- **QUEUED → PAIRED**: matchmaker pairs two compatible bots (same time-control pool).
- **PAIRED → IN_PROGRESS**: both bots present/ready; server sends the first `your_turn` to White and White's clock starts.
- **PAIRED → ABORTED**: a bot fails to ready within the start-grace window (no result).
- **IN_PROGRESS → FINISHED**: any decisive/draw termination in ADR-0008 (checkmate, timeout, resignation, illegal-move, disconnect-forfeit, stalemate, agreement, …).
- **IN_PROGRESS → ABORTED**: only the unrecoverable case where no fair result exists (e.g. both seats drop and neither reconnects, or a server fault). Single-side disconnect is a **forfeit → FINISHED**, not an abort.

Terminal states (FINISHED, ABORTED) are immutable once entered.

## Alternatives considered
- **Adding a `DISCONNECTED` Game state** — rejected; disconnect is per-seat and both seats keep the Game IN_PROGRESS. A game-level state would duplicate seat state and complicate clocks.
- **Folding QUEUED into the Game entity** — rejected; there's no opponent/Game yet, so QUEUED lives on the MatchmakingTicket, which *becomes* a Game at pairing.

## Consequences
- Positive: one authoritative machine every subsystem keys off; clean separation of ticket vs game; reconnect handled below the state layer.
- Negative / costs: need a start-grace timer (PAIRED→ABORTED) distinct from the in-game reconnect window (I5) — see new E7.
- Follow-on questions opened:
  - E7: start-grace window duration for PAIRED→ABORTED.
  - I7: exact rule for double-disconnect during IN_PROGRESS → ABORTED (no result) vs draw — confirm "no result."
