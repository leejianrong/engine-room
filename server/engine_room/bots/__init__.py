"""Bot management (ADR-0009, ADR-0014, ADR-0019) — the REST surface a user uses
to create/list/delete their bots and generate/rotate the per-bot API key.
"""

MAX_BOTS_PER_USER = 5  # ADR-0019 H1 (a future Premium lever)
