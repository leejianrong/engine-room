## What

<!-- What does this PR change? One or two sentences. Link the ticket, e.g. KAN-123. -->

## Why

<!-- The motivation / problem being solved. Skip if obvious from What. -->

## Test evidence

<!-- Which checks ran and their result. Delete lines that don't apply. -->

- [ ] `ruff check .` + `pytest tests/unit` (fast gate / pre-push)
- [ ] `pytest tests/integration` (needs Docker)
- [ ] `frontend`: `npm run check`
- [ ] `sdk/engineroom`: unit tests
- [ ] Playwright `e2e`
- [ ] Manual verification (describe below)

<!-- Paste key output / describe what you exercised. -->

## OPS notes

<!-- Anything a deployer/reviewer must know. Write "none" if there's nothing. -->

- **DB migration:** none / Alembic revision `____`
- **Secrets / config:** none / new env var `____`
- **Deploy impact:** none / `fly deploy --config server/fly.toml` / manual step required
