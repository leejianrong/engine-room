# ADR-0019: Abuse prevention — caps, rate limits, griefing cooldowns, human gate

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
REQS asks how to stop a malicious user flooding the system (e.g. 500 dummy bots). Answers QUESTIONS H1, H2, H3, H4; complements same-owner exclusion (ADR-0016 H5).

## Decision
- **H1 — Bots per User: 5** at MVP. Explicitly a **future monetization lever** — a Premium tier can raise the cap. Since a Bot plays one Game at a time (ADR-0009), this also caps concurrent games per User at ≤5; no separate concurrent-game cap needed.
- **H2 — Rate limits** (starting values, tunable):
  - WebSocket connect/handshake: capped per User/IP per minute.
  - Queue/ticket creation: capped per Bot per minute.
  - Inbound messages per Session: capped well above legitimate Blitz cadence; excess → disconnect (anti-flood / anti-DoS).
- **H3 — Griefing cooldowns.** Track per-Bot **disconnect / abort / illegal-move rates**. Repeat offenders get a **soft, escalating temp-cooldown** (matchmaking/queue timeout for N minutes), not a permanent ban at MVP.
- **H4 — Human gate = a valid GitHub account** via OAuth (ADR-0013). No captcha at MVP. GitHub **account age** may be used later as a weak throwaway-account signal.

## Alternatives considered
- **No bot cap / unlimited** — rejected; that's the flood attack REQS calls out.
- **Hard permanent bans for griefing** — rejected at MVP; soft escalating cooldowns are less punishing to flaky-but-honest bots and reversible.
- **Captcha / email-verify gate** — unnecessary given GitHub OAuth already proves a real account; deferred.

## Consequences
- Positive: caps + same-owner exclusion (ADR-0016) + rate limits together answer the REQS "500 dummy bots" concern; monetization hook comes for free from the bot cap.
- Negative / costs: a determined attacker with many GitHub accounts can still register 5 bots each — higher-effort, **accepted / out of scope for MVP** (IP + account-age heuristics are a later escalation). Rate-limit and cooldown counters need a home (Redis, alongside the queues — see ADR-0020).
- Follow-on questions opened: exact numeric limits and cooldown escalation curve (tune with data); Premium tier mechanics (future, business).
