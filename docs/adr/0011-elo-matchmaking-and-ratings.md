# ADR-0011: Elo-based matchmaking with per-Bot ratings (MVP)

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude
- **Amends:** ADR-0009 (promotes Bot `rating` from future → MVP)

## Context
We must choose the MVP pairing policy. REQS lists an Elo leaderboard as a *nice-to-have*, but we are electing to ship **Elo-based pairing from day one**, which requires ratings to be a first-class, persisted Bot attribute now. Answers QUESTIONS E1; promotes the rating field in ADR-0009.

## Decision

**Ratings.** Every **Bot** carries a persisted integer **Elo rating** (per Bot, not per User).
- Initial rating: **1200** (recommendation).
- Score per game: win = 1, draw = 0.5, loss = 0; standard Elo expected-score update on both bots.
- **K-factor:** 32 while *provisional* (first ~30 rated games), 16 thereafter (recommendation).
- Ratings update **only when a Game reaches FINISHED** (ADR-0010) — including decisive terminations like timeout, resignation, illegal-move, and disconnect-forfeit (ADR-0008), since those are real results. **ABORTED games do not affect rating.**

**Pairing = widening-window over a pool.** A Bot's MatchmakingTicket enters a pool; the matchmaker pairs it with the **closest-rated waiting opponent within a rating window that starts narrow and widens with wait time**, falling back to "closest available / anyone" after a timeout. (Pure same-rating pairing is impossible at low volume — this is the honest form of Elo pairing.)

## Alternatives considered
- **Random / FIFO pairing at MVP, Elo deferred** — simplest; matches REQS's "nice-to-have" framing. Rejected by explicit choice to make competitive ranking a core day-one draw.
- **Glicko/Glicko-2** — better at rating uncertainty and inactivity than Elo, but more complex. Deferred; Elo is adequate and well-understood for MVP.

## Consequences
- Positive: competitive ranking is core from launch; the REQS leaderboard nice-to-have becomes nearly free (it's a view over existing ratings). Draws are handled natively by Elo.
- Negative / costs:
  - **Low-volume degradation** — with few bots online, pairing falls back to "closest available"; mismatched pairings early are expected, not a bug.
  - **Cold start** — uniform initial ratings make the first ~dozens of games near-random until ratings diverge.
  - **Rating-farming abuse vector** — a User owning many Bots can self-play to inflate a bot's rating (→ new H5).
  - Ratings need a home in Postgres and an update step in the game-finalization path.
- Follow-on questions opened:
  - E8: numeric knobs — initial rating, K-factor thresholds, starting window (±?), widen rate, fallback timeout.
  - E2 (still to grill): are pools — and later ratings — segmented **by time control** (3+0 vs 5+0)?
  - H5: defend against self-play rating farming (rate-limit rematches between commonly-owned bots? flag suspicious pairs?).
