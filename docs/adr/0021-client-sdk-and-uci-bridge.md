# ADR-0021: Official Python SDK + client-side UCI bridge, as a decoupled repo

- **Status:** accepted
- **Date:** 2026-07-07
- **Deciders:** leejianrong, Claude

## Context
Adoption for a hobbyist/AI-student audience hinges on how fast they can get a bot playing. REQS asks whether to ship an official wrapper (its third open question). Answers QUESTIONS L1, L2; resolves the B6 protocol-version residual.

## Decision
- **L1 — Official Python SDK at launch** (`engineroom`, pip-published). Framework-style: the user subclasses a `Bot` and implements `choose_move(board) -> move` (board is a `python-chess` object). The SDK owns the WebSocket transport, the authenticated handshake and reconnect (ADR-0014), heartbeats, protocol (de)serialization, and surfacing clock/state. Python first because it matches the backend, `python-chess` (ADR-0006), and the audience's lingua franca. Other languages deferred.
- **L2 — Client-side UCI bridge**, shipped with the SDK: a `Bot` whose `choose_move` delegates to a local UCI engine subprocess via `python-chess`'s built-in `chess.engine`. Runs entirely on the user's machine, so it does **not** reintroduce native UCI on the server (respects REQS out-of-scope). Lets people point an existing engine (e.g. Stockfish) at the platform without rewriting it.
- **Decoupling (explicit requirement):** the SDK lives in its **own repository**, independently versioned and published. It depends only on a **public, versioned wire-protocol spec** — never on server internal code. Server and SDK share the *contract*, not code.
- **Protocol version (resolves B6):** the handshake carries a **protocol version**; server and SDK evolve independently with a compatibility check.

## Alternatives considered
- **No SDK (raw protocol only)** — rejected; kills the hobbyist onramp.
- **Multi-language SDKs at launch** — deferred; Python first, protocol spec enables others later.
- **Server-side UCI** — rejected per REQS; the bridge is client-side instead.
- **SDK in the server monorepo** — rejected per the decoupling requirement (a shared *protocol-spec* artifact is acceptable; shared server code is not).

## Consequences
- Positive: signup-to-first-move in minutes; UCI bridge is a near-free killer onramp (thanks to `python-chess`); clean independent versioning; the protocol becomes a first-class, documented contract. The SDK's reference bots double as the house bots (ADR-0022).
- Negative / costs: the wire-protocol spec is now a maintained artifact with compatibility obligations; SDK is a second release surface.
- Follow-on questions opened: ~~where the protocol spec lives~~ → drafted in [PROTOCOL.md](../design/PROTOCOL.md) (v1.0); a machine-readable JSON-Schema derivation and the SDK support/versioning matrix remain future work.

## Addendum (2026-07-09, V7): built — monorepo-package-first (extract-on-publish deferred)
The SDK landed as **`sdk/engineroom`**, a decoupled `uv` package **inside the monorepo** rather than a standalone repo from day one (V7 Q1, owner call). The decoupling this ADR actually requires — **no dependency on server internal code** — is preserved and *enforced*: an AST import-boundary test asserts the package imports no `engine_room`; the shared artifact is the wire spec (PROTOCOL.md), not code. The wire loop was **extracted from `devtools/demo_bot`** (a proven V4/V5 client) into a `Bot` base class whose sole required override is `choose_move(board)`; the loop hides the handshake, reconnect (§8), `ply`-idempotency (§9), and heartbeats (§10). The **UCI bridge (L2)** shipped inside the SDK as `engineroom.uci.UCIBot` + a `engineroom-uci` console script. The **protocol-version handshake (B6)** is sent in `hello`; the SDK raises a friendly error on `VERSION_UNSUPPORTED`. The *literal* separate-repo split + **PyPI publish** is a tracked follow-up (V7 **O-2**: a git-subtree/`filter-repo` split + a publish job needing an owner PyPI account); until then the quickstart path-installs the SDK. See docs/shaping/V7-plan.md.
