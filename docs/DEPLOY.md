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

## 7. Frontend (separate origin) — Fly static
The SvelteKit dashboard (V6) ships as a **second Fly app** (`engine-room-web`), a stateless static
site: the existing multi-stage [`frontend/Dockerfile`](../frontend/Dockerfile) runs `npm run build`
then serves `/app/build` with nginx on port 80. It is separate from the backend app and has no
in-memory state, so scale-to-zero is fine (unlike the backend). Config: [`frontend/fly.toml`](../frontend/fly.toml).

> **`VITE_API_BASE` is baked at BUILD time.** The browser bundle hard-codes the backend base URL at
> `npm run build`, so the image must be built pointing at the backend's **public** URL. It is pinned
> in `frontend/fly.toml` `[build.args]` (`VITE_API_BASE = "https://engine-room.fly.dev"`); re-pointing
> requires a rebuild, not a runtime env change. Override for a one-off with `--build-arg`.

### 7a. Create the app + first deploy (manual)
```bash
cd frontend
fly apps create engine-room-web          # matches `app` in frontend/fly.toml
# Baked-in backend URL comes from fly.toml [build.args]; override with --build-arg to re-point:
fly deploy --remote-only --build-arg VITE_API_BASE=https://engine-room.fly.dev
curl -I https://engine-room-web.fly.dev/  # 200 from nginx
```

### 7b. Add the frontend origin to backend CORS
The browser calls the API cross-origin, so the backend must allow this origin. Update the backend
secret (see step 3) to include it (JSON list — keep any existing origins):
```bash
cd ../server
fly secrets set ER_CORS_ALLOW_ORIGINS='["https://engine-room-web.fly.dev"]'
```
Bearer-JWT auth is cross-origin-friendly, so no same-origin/reverse-proxy setup is required.

### 7c. Arm CI-gated frontend deploys (optional, recommended)
Mirrors step 6, but a **separate app-scoped token** and its own gate var. The backend's
`FLY_API_TOKEN` is scoped to the `engine-room` app and cannot deploy `engine-room-web`, so the
frontend gets its own token:
```bash
cd frontend
fly tokens create deploy -x 999999h                     # app-scoped to engine-room-web (run from frontend/)
gh secret set FLY_FRONTEND_API_TOKEN --body '<token>'   # repo secret
gh variable set FRONTEND_DEPLOY_ENABLED --body 'true'   # arms .github/workflows/deploy-frontend.yml
```
Thereafter: merge to `main` → CI runs → on green, `deploy-frontend.yml` ships the validated commit
(distinct `concurrency` group from the backend, so both deploys run independently). Un-arm anytime
with `gh variable set FRONTEND_DEPLOY_ENABLED --body 'false'`.

## Operating notes
- **Redeploys drop live games** (single in-memory worker) — expected; deploy during quiet periods.
- **Scaling:** stay at one machine. Real horizontal scale is the ADR-0020 Redis-bridge (future).
- **Migrations** run on every machine start (`alembic upgrade head`); a bad migration fails the
  boot and blocks the deploy (Fly health check) rather than corrupting a running instance.
- **Neon free tier** may cold-start its compute after idle (~1–2s on the first query); the health
  check `grace_period` covers boot.
