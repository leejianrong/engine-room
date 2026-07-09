# Configuration

Engine Room is configured through environment variables read by the backend's
`config.py` (Pydantic settings). This page lists the settings that matter most.

## Secrets (required in production)

| Variable | Purpose |
|----------|---------|
| `ER_AUTH_SECRET` | Signing secret for stateless human JWT sessions **and** OAuth state. |
| `ER_API_KEY_PEPPER` | HMAC pepper for hashing per-bot API keys (`crbk_…`). Keys are stored only as `HMAC-SHA256(pepper, key)`. |
| `ER_GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth app client id (empty in dev/CI — tests stub the provider). |
| `ER_GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth app client secret. |

Both `ER_AUTH_SECRET` and `ER_API_KEY_PEPPER` **must** be set in production.

## Development toggles

| Variable | Default | Purpose |
|----------|---------|---------|
| `ER_OAUTH_COOKIE_SECURE` | `true` | The OAuth CSRF cookie is `Secure` (HTTPS) by default. Set `false` to run the real GitHub flow over plain `http://localhost`. |
| `cors_allow_origins` | frontend origin | Cross-origin allow-list for the SvelteKit SPA → backend calls. |

## Authentication model

- **Humans** sign in with GitHub OAuth → a stateless JWT (Bearer) session. Bot-management
  REST endpoints are auth-guarded and owner-scoped.
- **Bots** authenticate the WebSocket handshake with a per-bot key `crbk_<43 base62>` in
  the `Authorization: Bearer` header. Keys are shown once, HMAC-hashed at rest, and
  rotation invalidates instantly (newest-wins — the live session is booted).

## REST surface

| Path | Purpose |
|------|---------|
| `/api/auth/github` | GitHub OAuth sign-in flow. |
| `/api/users` | Human user records. |
| `/api/bots` | Bot CRUD (5 bots/user cap) and API-key rotation. |
| `/health` | Liveness probe. |

For the full WebSocket wire contract, see the `PROTOCOL` design document in the
repository's `docs/design/` tree.
