# REQS

## Idea (one-liner)

A real-time matchmaking and spectating platform built specifically for AI bots and algorithmic chess engines to compete against each other.

## Problem — what's broken today, and for whom

* **For AI developers and hobbyists:** There is no modern, casual "Chess.com" equivalent for automated players. Testing a custom chess bot against others requires setting up complex local servers, configuring cumbersome legacy protocols, or joining highly formal, slow-moving computer chess tournaments.
* **For spectators:** Watching top-tier computer chess (like TCEC) feels rigid, stale, and unapproachable. There is no central, hype-filled platform where people can casually log on, watch live bot matchups in real time, and see dynamic algorithmic strategies clash on a whim.
* **The friction:** Existing systems are trapped in 1990s desktop-first architecture, making automated matchmaking incredibly high-friction to set up.

## Users / who it's for

* **Bot Creators:** Software engineers, AI students, and chess engine hobbyists who want to deploy their code and see how it ranks against other algorithms in active matchmaking pools.
* **Human Spectators:** Chess fans and tech enthusiasts who want to watch fast-paced, high-level, real-time algorithmic games with clean, responsive visuals.

## Core outcomes (what it must let people do)

* **Register a Bot Account:** A human user must be able to log in, create a profile, and generate a secure token/key specifically for their bot engine.
* **Queue for a Match:** An authenticated bot must be able to request a game and enter a live matchmaking pool.
* **Play a Game via API:** Two bots paired by the system must be able to stream the game state and execute standard chess moves back and forth with low latency.
* **Enforce the Game Clock:** The system must strictly track and enforce game time controls (e.g., Blitz clocks). If a bot takes too long to respond, it loses on time.
* **Live Spectating Dashboard:** Human users must be able to open a web browser, see a list of active games, and watch the chess pieces move in real time without refreshing the page.

## Nice-to-haves (maybe later)

* A formal Elo rating leaderboard for all registered bots.
* Historically saved game PGNs (game logs) and basic Win/Loss statistics for profiles.
* Support for automated mini-tournaments (e.g., hourly 8-bot brackets).

## Out of scope / not now

* **No Code Hosting / Compute Provisioning:** We are *not* running or hosting the user's code on our own infrastructure for the MVP. Users must run their own code locally or on their own cloud, connecting outward to our platform.
* **No Human vs. Bot Play:** This platform is strictly Bot vs. Bot. Humans can only manage settings and watch games, not play moves manually.
* **No Native Legacy Engine Support:** We will not natively accept raw, legacy desktop chess interface protocols (like UCI/XBoard) directly on the server. The MVP will require writing code against our modern web protocol.
* **No Anti-Cheat/Code Verification:** We will not attempt to verify if a user's code is unique or if they are secretly just copy-pasting Stockfish.

## Open questions / unknowns

* **Time Control Minimums:** What is the fastest game speed we can safely support (e.g., 1-minute Bullet) before external internet latency makes the game unfair for bots hosted far away from our servers?
* **Abuse Prevention:** How do we stop a malicious user from spamming the matchmaking queue with 500 identical dummy bots to flood the system?
* **Standardized Adapter:** Should we provide an official, pre-made wrapper script at launch so users can easily bridge their legacy engines to our platform, or should we leave the connection entirely up to them to implement?