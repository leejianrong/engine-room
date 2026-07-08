# Deploy runbook — Fly.io + Neon

Host decision + rationale: [ADR-0026](adr/0026-hosting-fly-neon.md). This is the
how-to. Backend (API + bot WebSocket) → **Fly.io**, one always-on machine.
Database → **Neon** managed Postgres. Frontend → any static host (separate
origin + CORS).

> **Single machine, on purpose.** Game state is in-memory in one process
> (ADR-0018/0020). Never `fly scale count > 1` and never enable scale-to-zero —
> it would split or kill live games. A deploy/restart drops in-progress games
> (accepted MVP risk).

## 0. One-time tooling
```bash
curl -L https://fly.io/install.sh | sh   # flyctl
fly auth login
```

## 1. Neon database
1. Create a project at neon.tech → copy the connection string. It looks like:
   `postgresql://USER:PASSWORD@ep-xxx.REGION.aws.neon.tech/DBNAME?sslmode=require&channel_binding=require`
2. Convert it for SQLAlchemy's **asyncpg** driver — change the scheme and use `ssl=require`
   (asyncpg rejects `sslmode`/`channel_binding`, so drop them):
   ```
   postgresql+asyncpg://USER:PASSWORD@ep-xxx.REGION.aws.neon.tech/DBNAME?ssl=require
   ```
   Keep this as `ER_DATABASE_URL` for step 3. (Migrations run automatically on deploy — the
   image's start command runs `alembic upgrade head` before uvicorn.)

## 2. Create the Fly app
```bash
cd server
fly apps create <your-app-name>          # then set `app = "<your-app-name>"` in fly.toml
# pick a region near you: fly platform regions
```

## 3. Secrets (never commit these)
```bash
cd server
fly secrets set \
  ER_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@ep-xxx.../DBNAME?ssl=require' \
  ER_AUTH_SECRET="$(openssl rand -hex 32)" \
  ER_API_KEY_PEPPER="$(openssl rand -hex 32)"
# GitHub OAuth (see step 5) — add once you've registered the OAuth app:
fly secrets set \
  ER_GITHUB_OAUTH_CLIENT_ID=... \
  ER_GITHUB_OAUTH_CLIENT_SECRET=... \
  ER_GITHUB_OAUTH_REDIRECT_URL='https://<your-app-name>.fly.dev/api/auth/github/callback'
# Frontend origin(s) for CORS (JSON list) once the frontend is deployed:
fly secrets set ER_CORS_ALLOW_ORIGINS='["https://your-frontend.example"]'
```
`ER_OAUTH_COOKIE_SECURE` defaults to `true` — correct for HTTPS prod; leave it unset.

## 4. First deploy (manual)
```bash
cd server
fly deploy --remote-only
fly logs                                  # watch migrations + boot
curl https://<your-app-name>.fly.dev/health   # {"status":"ok"}
fly scale count 1                         # ensure exactly one machine
```

## 5. GitHub OAuth app (for human login)
Register an OAuth app at github.com → Settings → Developer settings → OAuth Apps:
- **Homepage URL:** `https://<your-app-name>.fly.dev`
- **Authorization callback URL:** `https://<your-app-name>.fly.dev/api/auth/github/callback`

Copy the client id/secret into the secrets in step 3. Sign-in flow:
`GET https://<your-app-name>.fly.dev/api/auth/github/authorize` → redirects to GitHub →
callback returns a Bearer JWT.

## 6. Arm CI-gated deploys (optional, recommended)
After the first manual deploy works, let CI deploy every green `main`:
```bash
fly tokens create deploy -x 999999h            # a deploy token
gh secret set FLY_API_TOKEN --body '<token>'   # repo secret
gh variable set DEPLOY_ENABLED --body 'true'   # arms .github/workflows/deploy.yml
```
Thereafter: merge to `main` → CI runs → on green, `deploy.yml` ships the validated commit.
Un-arm anytime with `gh variable set DEPLOY_ENABLED --body 'false'`.

## 7. Frontend (separate origin)
The polished dashboard is V6; for now the SvelteKit `frontend/` can be built and hosted on any
static host, pointed at the Fly API base URL, with that origin added to `ER_CORS_ALLOW_ORIGINS`.
Bearer-JWT auth is cross-origin-friendly, so no same-origin/reverse-proxy setup is required.

## Operating notes
- **Redeploys drop live games** (single in-memory worker) — expected; deploy during quiet periods.
- **Scaling:** stay at one machine. Real horizontal scale is the ADR-0020 Redis-bridge (future).
- **Migrations** run on every machine start (`alembic upgrade head`); a bad migration fails the
  boot and blocks the deploy (Fly health check) rather than corrupting a running instance.
- **Neon free tier** may cold-start its compute after idle (~1–2s on the first query); the health
  check `grace_period` covers boot.
