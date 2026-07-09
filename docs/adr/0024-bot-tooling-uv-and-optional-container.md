# ADR-0024: Bot tooling — uv + pyproject.toml; container optional, not default

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude
- **Amends:** ADR-0021 (SDK packaging), ADR-0022 (onboarding step 3)

## Context
The SDK and quickstart need a packaging/run story. The primary user is the AI/CS student, whose success criterion is "zero → live game in minutes, no plumbing" (ADR-0023). Refines the onboarding tooling.

## Decision
- The SDK and quickstart use **`uv` + `pyproject.toml`** (with `uv.lock`), **not** `pip` + `requirements.txt`. Onboarding step 3 becomes `git clone <quickstart> && uv sync`; run with `uv run python bot.py`.
- The **hero path is `uv`, no container.** A container is **offered as an optional path** — a `Dockerfile` included in the quickstart repo — but is not the default and not required.

## Alternatives considered
- **Container as the default/hero path** — rejected. It adds a heavyweight prerequisite (Docker installed + running; painful on Windows/WSL2) at the most fragile onboarding step, contradicting ADR-0023's "no plumbing" criterion; slows the beginner edit-run loop; and hides the code. `uv` already delivers most of the reproducibility benefit (locked deps + managed Python version) for a pure-Python **outbound WebSocket client** (ADR-0002) that has no inbound ports or system daemons — so a container is ceremony without a matching problem for the primary user.
- **pip + requirements.txt** — rejected in favor of `uv` (faster, reproducible via lockfile, managed Python version, no global-env pollution).

## Consequences
- Positive: fastest zero-to-first-move for the student; reproducible without Docker; the optional `Dockerfile` still serves the advanced/UCI-bridge persona (ADR-0021) and users mirroring a cloud deploy target — which aligns with ADR-0023's secondary-user ordering.
- Negative / costs: two supported run modes to document (keep the container clearly labeled "optional/advanced").
- Follow-on questions opened: none blocking (container base image + whether to publish it are build-time details).

## Addendum (2026-07-09, V7): realized as specified
The SDK and quickstart ship **`uv` + `pyproject.toml` + `uv.lock`**. The hero path is
`git clone → uv sync → uv run python random_bot.py` — no container. The **optional/advanced**
container is a `Dockerfile` in `sdk/quickstart`, clearly labeled optional (with a build-context note
while the SDK is path-installed pre-PyPI). `make sdk-bot` wires the whole flow. Matches this ADR
exactly. See docs/shaping/V7-plan.md.
