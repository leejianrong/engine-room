# ADR-0023: MVP scope & success definition

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
The closing decision: turn ADR-0001..0022 into an explicit "v1 is done when…" line, a scope boundary, and a primary-user success criterion. Answers QUESTIONS M1, M2, M3.

## Decision

**Demoable slice (v1-done bar).**
> A developer signs in with GitHub, creates a bot (receives a rotatable API key shown once), clones the quickstart, runs it, and within minutes watches their bot get matched against a house bot and play a full **3+0 Blitz** game to a real result — live on a public spectator dashboard, with the clock enforced server-side and the PGN saved to the bot's profile.

**Primary user: the AI/CS student writing their first chess bot from scratch.**
Success = the SDK + quickstart takes them **from zero to a live, watchable game in minutes, with no protocol plumbing**. Design implication: the **SDK / quickstart / `RandomBot` path is the hero flow**; the UCI bridge (ADR-0021) serves the secondary "existing-engine hobbyist" persona and gets secondary polish in v1.

**In scope for v1:**
- GitHub OAuth (ADR-0013); bot CRUD + rotatable per-bot API keys (ADR-0014).
- Python SDK + quickstart template + client-side UCI bridge (ADR-0021, ADR-0022).
- WebSocket game protocol, UCI moves + FEN state (ADR-0002, ADR-0007).
- `python-chess` rules + server-authoritative clock (3+0, 5+0), auto-draws, resign/draw-offer (ADR-0003, ADR-0006, ADR-0008, ADR-0016).
- Elo matchmaking: per-time-control pools, anonymous auto-pairing, house bots, same-owner exclusion (ADR-0011, ADR-0012, ADR-0016, ADR-0022).
- SSE spectating: live board, active-games lobby, catch-up + replay (ADR-0015, ADR-0016).
- Postgres records + PGNs + basic W/L game-history API (ADR-0018).
- Single-process deployment (ADR-0020); core abuse limits (ADR-0019).

**Deferred (post-v1):**
- Bullet (1+0) + RTT compensation; Redis-bridged multi-worker scale + live-state crash recovery; tournaments; Google/password auth; non-Python SDKs; Premium tier; a leaderboard *view* (data exists, UI later); per-time-control ratings; direct challenges.

## Alternatives considered
- **Broader v1** (tournaments / leaderboard UI / multi-worker) — rejected; each is cleanly deferrable behind the demoable slice and none is needed to prove the core loop.
- **Thinner v1** (drop PGNs/history) — rejected; they're near-free given Elo persistence and directly serve the bot-profile payoff.

## Consequences
- Positive: a crisp, testable definition of done anchored on one end-to-end flow; a clear build-priority order (hero path first); every v1 item traces to a prior ADR.
- Negative / costs: the student-first focus means the existing-engine hobbyist gets a rougher (though functional) v1 experience via the UCI bridge.
- Follow-on questions opened: none blocking — remaining items are tuning/build-time details tracked in QUESTIONS.md.
