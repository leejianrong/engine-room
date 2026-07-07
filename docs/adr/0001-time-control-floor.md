# ADR-0001: Blitz as the MVP time-control floor

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
REQS pitches a "hype-filled," "fast-paced," "low latency" experience and names Blitz clocks, while listing "fastest safe time control" as an open question. Critically, bots run on the **user's own machine or cloud** (no code hosting — see REQS out-of-scope), so we have no control over bot location or connection quality; uncontrolled RTT of 100–300ms is normal. Answers QUESTIONS C3, C4, and partially C2.

## Decision
MVP supports **Blitz** time controls, specifically **3+0 and 5+0** (base minutes + increment seconds). **Bullet (1+0) is deferred** until real-world latency has been measured in production and a fairness story exists. Time control is modeled as `{base_seconds, increment_seconds}` so faster/slower formats are a config change, not a redesign.

## Alternatives considered
- **Bullet (1+0) from day one** — max wow-factor, but at ~1s/move a 300ms RTT is a third of the think budget; forces RTT compensation + bot colocation, which fights the "run it anywhere" premise. High risk.
- **Rapid only (10+0+)** — latency becomes a non-issue but the "fast-paced/hype" product promise is lost.
- **Freeform knob, no floor** — avoids committing, but then nothing is tuned or tested well; fairness guarantees become vague.

## Consequences
- Positive: multi-second move budgets make network jitter negligible, so we can ship **without** RTT compensation (see ADR-0003) and still be fair. A full game finishes in minutes → good spectator hype. Directly answers the REQS "fastest safe time control" open question with "don't start at the dangerous end."
- Negative / costs: no sub-second Bullet excitement at launch; some users will ask for it.
- Follow-on questions opened: What increment values do we offer? Do we let match creators pick TC or is it fixed at MVP? (→ QUESTIONS E2, new C7 below.)
