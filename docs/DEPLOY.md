# Deploy runbook — Fly.io + Neon

Host decision + rationale: [ADR-0026](adr/0026-hosting-fly-neon.md). This is the
how-to. Backend (API + bot WebSocket) **and the SvelteKit SPA** → **ONE Fly.io app**,
one always-on machine. Database → **Neon** managed Postgres.

> **Single origin (V8, KAN-68).** The frontend is built into the backend image and
> served same-origin by uvicorn (Starlette `StaticFiles` + an SPA fallback — no
> nginx, no separate frontend app). One `fly deploy` ships both. CORS is therefore
> **optional** (only needed if you host the SPA on a *different* origin). This also
> means one URL for the browser and the bots, and clean same-origin auth cookies
> (see KAN-64).

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
```
`ER_OAUTH_COOKIE_SECURE` defaults to `true` — correct for HTTPS prod; leave it unset.
`ER_CORS_ALLOW_ORIGINS` is **not needed** — the SPA is served same-origin. Set it only
if you additionally host the frontend on a separate origin (JSON list of origins).

## 4. First deploy (manual)
Deploy **from the repo root** (not `cd server`): the image bakes the SPA in, so the
Docker build context must include `frontend/`. `server/fly.toml` points at
`server/Dockerfile`.
```bash
# from the repo root
fly deploy --remote-only --config server/fly.toml
fly logs                                  # watch the SPA build + migrations + boot
curl https://<your-app-name>.fly.dev/health   # {"status":"ok"}
curl -I https://<your-app-name>.fly.dev/      # 200 — the SPA index.html
fly scale count 1                         # ensure exactly one machine
```
The image's uvicorn CMD runs with `--proxy-headers --forwarded-allow-ips=*` so that
behind Fly's TLS proxy the app sees `https` — **required** for GitHub OAuth (otherwise
FastAPI-Users builds an `http://` redirect_uri that GitHub rejects).

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

## 7. Frontend — shipped in the backend image (same origin)
There is **no separate frontend app**. The SvelteKit SPA is built by a Node stage in
[`server/Dockerfile`](../server/Dockerfile) (`npm ci && npm run build` → `frontend/build`)
and copied into the backend image; `ER_STATIC_DIR` points the app at it and uvicorn serves
it same-origin (Starlette `StaticFiles` + an SPA fallback for client-side routes — no nginx).
The step-4 `fly deploy` already ships it. Verify:
```bash
curl -I https://<your-app-name>.fly.dev/          # 200 — index.html
curl    https://<your-app-name>.fly.dev/api/games # JSON — API still wins over the SPA fallback
curl -I https://<your-app-name>.fly.dev/watch     # 200 — SPA route (fallback to index.html)
```

- **No `VITE_API_BASE`.** The bundle calls the API with a **relative** base (`''`), so it hits
  whatever origin served the page. `VITE_API_BASE` remains an override only for hosting the SPA
  elsewhere.
- **CORS is optional.** Same-origin needs no `ER_CORS_ALLOW_ORIGINS`. The middleware + env are
  kept (harmless) purely for an external-origin frontend.
- **Local dev** stays two processes (`make dev`): Vite on :5174 proxies `/api`, `/auth`, `/users`
  to the backend on :8001 (see `frontend/vite.config.ts`), so it's same-origin with no dev CORS.

## Operating notes
- **Redeploys drop live games** (single in-memory worker) — expected; deploy during quiet periods.
- **Scaling:** stay at one machine. Real horizontal scale is the ADR-0020 Redis-bridge (future).
- **Migrations** run on every machine start (`alembic upgrade head`); a bad migration fails the
  boot and blocks the deploy (Fly health check) rather than corrupting a running instance.
- **Neon free tier** may cold-start its compute after idle (~1–2s on the first query); the health
  check `grace_period` covers boot.
