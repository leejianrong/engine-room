"""Tournaments (KAN-56) — persisted round-robin events with bot opt-in via seek.

Single-process/in-memory-orchestrated, mirroring `MatchmakingQueue`: a
`TournamentManager` lives on `app.state`, enrolls bots (a `seek` carrying a
`tournament_id`), generates the round-robin schedule at start, launches each game
over the existing `GameLauncher`, and writes standings back to Postgres as games
finalize. Only the round-robin format is built in this slice; swiss + elimination
brackets, and the SvelteKit UI, are deferred follow-up cards.
"""
