"""Developer-only tooling — NOT imported by the app.

Local conveniences for running/seeing the platform without the full GitHub OAuth
flow: `mint_bot` provisions a real per-bot API key straight from the DB, and
`demo_bot` connects a random-mover bot so there's a live game to spectate (there
is no lobby until V6). These use the *production* key path (no auth bypass) — they
just skip the browser round-trip. Never wired into `create_app`.
"""
