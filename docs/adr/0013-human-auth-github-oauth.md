# ADR-0013: Human authentication — GitHub OAuth via a modular auth layer

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Ownership, ratings, and bot management (ADR-0009, ADR-0011) require real human accounts. Our audience is developers. Answers QUESTIONS G1.

## Decision
Human login at MVP is **GitHub OAuth**. The auth layer is built on **FastAPI-Users** and kept **modular/provider-agnostic**, so **Google OAuth and email+password backends can be added later** without reworking the User model or session handling.

## Alternatives considered
- **Email + password only at MVP** — more code to handle safely (hashing, reset, verification) for an audience that mostly has GitHub accounts. Deferred (still supported later via FastAPI-Users).
- **Roll-our-own auth** — rejected; FastAPI-Users gives OAuth, sessions, and future password/verification flows for free and fits FastAPI + Postgres.

## Consequences
- Positive: zero password handling at MVP; devs sign in with an account they already have; a clear path to add Google/password without migration.
- Negative / costs: a hard GitHub dependency for launch (users without GitHub are excluded until Google/password land); OAuth app registration + callback config required.
- Follow-on questions opened:
  - H4: do we need email verification / human-check before issuing bot keys? (With OAuth the GitHub account is the identity — likely deferrable.)
  - User↔Bot ownership records live alongside the FastAPI-Users user table in Postgres (ADR-0005).
