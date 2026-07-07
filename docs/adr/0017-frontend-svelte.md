# ADR-0017: Frontend framework — Svelte (MVP)

- **Status:** accepted (recommendation — flip to React on preference)
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
ADR-0005 set TypeScript for the frontend but left the framework open (QUESTIONS N1). The frontend is a focused, reactive real-time UI: a live board driven by an SSE stream (ADR-0015) plus a lobby list and bot-management screens.

## Decision
Use **Svelte** (TypeScript). Low ceremony and excellent ergonomics for reactive real-time UI (an SSE-driven board is idiomatic with Svelte stores). This choice is **low-coupling and reversible early** — flip to **React** if ecosystem breadth, component libraries, or team familiarity matter more.

## Alternatives considered
- **React** — largest ecosystem and hiring pool, more component libraries; more boilerplate for this small a UI. A fine alternative; the flip cost is low at MVP.
- **Vanilla TS / lit** — minimal deps but more manual reactivity plumbing for the live board.

## Consequences
- Positive: fast to build a snappy live board; small bundle; clean reactivity for streaming updates.
- Negative / costs: smaller ecosystem/hiring pool than React; if the team is React-native this adds a learning curve — hence the explicit flip option.
- Follow-on questions opened: none blocking; component/styling choices deferred to build time.
