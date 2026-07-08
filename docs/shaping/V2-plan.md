---
shaping: true
---

# V2 Plan — Real identity

**Status: 🟢 CONFIRMED — implementing (2026-07-08).** The four open decisions (D-i … D-l)
were confirmed by the owner on 2026-07-08 (all four recommendations accepted). All decisions
are now pinned; implementation proceeds sub-step by sub-step on `feat/v2-identity`.

Implementation plan for slice **V2** (from Shape A, part A2). Higher levels:
[slices.md](slices.md) (V2 row), [shaping.md](shaping.md) (R's, Shape A, A2 thickening row).
Mirrors the format of [V1-plan.md](V1-plan.md). Ground truth remains the ADRs + [PROTOCOL.md](../design/PROTOCOL.md);
where this plan and the docs disagree, the code wins and the docs get updated (CLAUDE.md).

## Goal (definition of done)
A developer opens the site, **signs in with GitHub**, **creates a Bot** and is shown its
**API key exactly once**. Pointing a client at `/api/bot/v1` with `Authorization: Bearer <that key>`
authenticates as **that real Bot** (V1's stub dev-token is gone) and plays a full 3+0 game —
the game_start opponent, `welcome.bot`, and the persisted `games` row all carry the **real Bot
identity** (via `white_bot_id`/`black_bot_id` FKs). Rotating the key **instantly** invalidates the
old one and boots any live session using it. A second authenticated connection for the same Bot
**replaces** the first (newest-wins). The 5-bots-per-user cap is enforced. The whole surface is
exercised by REST integration tests (real Postgres) + the WS-seam unit tests (DB-free).

## What thickens (A2 → V2)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> N1 stub-auth → GitHub OAuth + hashed rotatable key at handshake; adds a REST bot-CRUD place + newest-wins session.

No new *subsystems* — V2 thickens N1 (handshake auth) and adds the human/management REST surface
that was always contract-external to PROTOCOL.md (PROTOCOL.md §intro: "Human/management APIs … are
**not** covered here"). Gameplay (N2–N10) is untouched except the finalizer now writes bot FKs.

## Build-time decisions

### Pinned (rationale below; open to correction)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **Auth library: FastAPI-Users** (`fastapi-users[sqlalchemy]` + `httpx-oauth`) | ADR-0013 mandates it; gives OAuth + sessions + a future password/Google path with no User-model rework. |
| D-b | **All ORM tables share the one `Base`** in `persistence/models.py` (User, OAuthAccount, Bot added there); feature logic/routes live in `auth/` and `bots/` | Keeps Alembic's `target_metadata` complete (env.py already binds `Base.metadata`); mirrors V1's single-Base layout. |
| D-c | **DI mirrors V1:** a `BotAuthenticator` seam + a live-`SessionRegistry` are injected via `create_app(...)`/`app.state`, exactly like `finalizer` | WS-seam unit tests stay DB-free by injecting a fake authenticator; production wires the Postgres-backed one. Same philosophy as `create_app(finalizer=…)`. |
| D-d | **User id = UUID** (FastAPI-Users `SQLAlchemyBaseUserTableUUID`); **Bot id = prefixed string** `bot_<hex>` (existing `new_id`) | FastAPI-Users' native pk is UUID; Bot keeps the opaque-prefixed scheme already used on the wire (`welcome.bot.id`, `opponent.id`). |
| D-e | **House bot becomes a real `bots` row** — id `bot_house_random` (already its `BotInfo.id`), `owner_id = NULL`, `is_house = true`, rating 1200, no API key | Lets `games.white_bot_id`/`black_bot_id` be real FKs without a magic system user; V3 same-owner exclusion treats NULL-owner house bots as exempt. |
| D-f | **`games` gains nullable `white_bot_id`/`black_bot_id` FKs with `ON DELETE SET NULL`; the V1 `white_name`/`black_name` columns are KEPT as a denormalized name snapshot** | US 9 lets a user delete a Bot; historical games must survive. FK → SET NULL preserves the row; the name snapshot keeps history readable without a join. (Deviates from the kickoff's "replacing" — see Open items O-1; confirm if you'd rather hard-drop the names.) |
| D-g | **5-bots-per-user cap** (ADR-0019 H1) enforced in the create service; house bots (NULL owner) don't count | ADR-0019; a `SELECT count(*) WHERE owner_id = :user` guard, 6th create → HTTP 409. |
| D-h | **Newest-wins scope = live-session replacement only** (a 2nd handshake for a Bot closes the 1st socket; rotation closes the live socket). **Game-seat *reconnect/resume* stays V4.** | ADR-0016 A6 is the session-collision rule; `welcome.active_game` resume is A4/V4 (shaping.md). V2 proves replacement, not mid-game seat rebind. |
| D-m | **MVP scope held:** single process, no Redis, Blitz only; ports :8001/:5174/:5433; frontend↔backend CORS | R5; unchanged from V1. Rate limits / griefing cooldowns (ADR-0019 H2/H3) stay V-later (need a counter home, ADR-0020) — not V2. |

### Confirmed 2026-07-08 (the four formerly-open decisions)
| # | Decision | Confirmed choice |
|---|----------|------------------|
| D-i | **OAuth in tests (stub the provider)** | Test bot-CRUD/keys via `app.dependency_overrides[current_active_user]` (DB-free where possible), **plus** one integration test that monkeypatches the `httpx-oauth` GitHub client (`get_access_token`/`get_id_email`) to drive the real callback → user-creation path. Mirrors V1's `create_app(finalizer=…)` DI style. |
| D-j | **Frontend in V2** | **REST API + OAuth routes only** — no new Svelte pages. Demo = GitHub login in the browser (redirect) → create bot & reveal key via REST (httpie) → point client at WS → existing spectator page shows the game. Keeps V2 thin (R5); the bot-management UI is V6's slice. ⇒ **sub-step 7 is dropped.** |
| D-k | **API-key format + hashing** | Token `crbk_<43-char base62>` (~256 bits), display prefix `crbk_<first 8>…`. **HMAC-SHA256(server pepper, token)** stored as an indexed unique `key_hash` — O(1) handshake lookup, DB-leak-safe (pepper needed too), no per-row salt for a high-entropy secret. Pepper via `ER_API_KEY_PEPPER` (required in prod; test/dev default). Deviates from ADR-0014's literal "salted"; honors its intent (hashed, DB-leak-safe) — noted in Open items O-4. |
| D-l | **FastAPI-Users session/token store** | **Stateless JWT strategy** (no store, no Redis, no session table). Transport: **Bearer** (the demo/tests are REST-driven per D-j; no browser SPA session to protect). Secret via `ER_AUTH_SECRET`. Revocation is coarse (expiry); fine for MVP. |

## Project layout (additions this slice)
```
server/engine_room/
  auth/
    users.py          # UserManager, get_user_db, SQLAlchemyUserDatabase adapter
    backend.py        # AuthenticationBackend (transport + strategy per D-l)
    oauth.py          # httpx-oauth GitHub client + FastAPI-Users OAuth router
    deps.py           # current_active_user (+ optional) dependencies
    schemas.py        # UserRead / UserCreate / UserUpdate (pydantic)
  bots/
    keys.py           # crbk_ token generation + hashing/verify (per D-k)
    service.py        # create/list/get/delete/rotate + 5-cap; owner scoping
    routes.py         # REST: /api/bots ... (auth-guarded)
    schemas.py        # BotCreate / BotRead / BotWithKey (key shown once)
    authenticator.py  # PostgresBotAuthenticator: Bearer key -> Bot identity (WS seam)
  ws/
    session_registry.py  # in-memory {bot_id: Session}; newest-wins replace/evict
  persistence/models.py  # + User, OAuthAccount, Bot (share Base)
  alembic/versions/0002_identity.py
# frontend/ — untouched this slice (D-j: REST + OAuth only; bot-management UI is V6)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| N1 handshake auth (thickened) | `ws/bot_endpoint.py` + `bots/authenticator.py` | Bearer key → `BotAuthenticator.authenticate()` → real `BotInfo`; UNAUTHORIZED close on miss (replaces dev-token check). |
| Newest-wins session | `ws/session_registry.py` | On welcome: register session under `bot_id`, close any prior live socket. On rotation: evict + close. |
| Human OAuth (US 1–4) | `auth/oauth.py`, `auth/backend.py`, `auth/users.py` | FastAPI-Users GitHub OAuth router; modular for Google/password later. |
| Bot CRUD (US 5–9) | `bots/routes.py` + `bots/service.py` | owner-scoped; 5-cap; delete → games FK SET NULL. |
| API keys (US 10–14) | `bots/keys.py` + `bots/service.py` | generate once, hashed at rest, rotate invalidates instantly. |
| games bot FKs (N8/N10) | `persistence/models.py`, `persistence/finalize.py`, `0002` | finalizer writes `white_bot_id`/`black_bot_id`. |

## Data model (Alembic `0002_identity`, down_revision `0001`)
```python
# users  (FastAPI-Users SQLAlchemyBaseUserTableUUID)
#   id UUID pk · email (unique, indexed) · hashed_password (nullable — OAuth users) ·
#   is_active · is_superuser · is_verified
# oauth_account  (SQLAlchemyBaseOAuthAccountTableUUID)
#   id · user_id FK->users(id) ON DELETE CASCADE · oauth_name · access_token ·
#   expires_at · refresh_token · account_id (indexed) · account_email
class Bot(Base):
    __tablename__ = "bots"
    id: Mapped[str]          = mapped_column(String(40), primary_key=True)   # bot_...
    owner_id: Mapped[UUID|None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)  # NULL = house
    name: Mapped[str]        = mapped_column(String(64))
    description: Mapped[str]  = mapped_column(String(256), default="")
    rating: Mapped[int]      = mapped_column(Integer, default=1200)          # US 8; moves in V5
    is_house: Mapped[bool]   = mapped_column(Boolean, default=False)
    key_hash: Mapped[str|None]   = mapped_column(String(128), unique=True, index=True, nullable=True)  # per D-k
    key_prefix: Mapped[str|None] = mapped_column(String(16), nullable=True)  # crbk_xxxxxxxx… for display
    key_created_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

# games: ADD nullable FKs; KEEP white_name/black_name (D-f)
#   white_bot_id String(40) FK->bots(id) ON DELETE SET NULL, nullable
#   black_bot_id String(40) FK->bots(id) ON DELETE SET NULL, nullable
# Migration also SEEDS the house bot row (id=bot_house_random, is_house=true, owner NULL).
```
Note: the integration fixture uses `Base.metadata.create_all` (WORKFLOW-ADOPTION divergence),
so new tables appear automatically there; `0002` is what runs in real dev/CI migrations. Consider
switching the fixture to run real migrations as a follow-up (already flagged in WORKFLOW-ADOPTION).

## Key contracts
```python
# bots/authenticator.py — the WS auth seam (injected, mirrors finalizer DI, D-c)
class BotAuthenticator(Protocol):
    async def authenticate(self, bearer_key: str) -> BotInfo | None: ...
# PostgresBotAuthenticator: hash(key) -> SELECT bots WHERE key_hash = :h -> BotInfo
# FakeAuthenticator(mapping): unit-test double, no DB

# ws/session_registry.py — newest-wins (ADR-0016 A6), single process (D-h)
class SessionRegistry:
    def register(self, session) -> Session | None: ...  # returns evicted prior, if any
    def evict(self, bot_id: str) -> Session | None: ...  # used by key rotation
    def current(self, bot_id: str) -> Session | None: ...

# bots/keys.py (per D-k, exact impl pinned once D-k confirmed)
def generate_key() -> tuple[str, str, str]: ...  # (plaintext, key_hash, key_prefix)
def hash_key(plaintext: str) -> str: ...          # deterministic → indexable lookup
```

## Newest-wins mechanics (D-h)
1. Handshake authenticates → build `Session` with the real `BotInfo`.
2. After `welcome`, `registry.register(session)`; if a prior live session existed, send it a
   fatal `error{code:"UNAUTHORIZED"?/"REPLACED"}` (code TBD in impl) and close its socket (1008).
3. On `WebSocketDisconnect`, remove the session from the registry **iff it is still current**
   (don't evict the replacement).
4. On key **rotation**, `registry.evict(bot_id)` closes the live socket immediately (ADR-0014
   "rotation invalidates the old key instantly … any live Session … is terminated").

## Build sub-steps (order within V2) — each ends in a demoable/testable checkpoint
1. **Deps + Users + auth backend + migration scaffold.** Add `fastapi-users[sqlalchemy]`,
   `httpx-oauth`; User/OAuthAccount models on `Base`; UserManager/adapter/auth-backend (per D-l);
   `current_active_user` dep; Alembic `0002` creating `users`+`oauth_account`. **Checkpoint:**
   app boots, FastAPI-Users routes mounted, `0002` applies (integration migration test).
2. **GitHub OAuth flow.** Mount the OAuth router (authorize + callback); GitHub client from
   config (`ER_GITHUB_CLIENT_ID`/`_SECRET`). **Checkpoint:** integration test with a **stubbed
   provider (D-i)** drives callback → `users`+`oauth_account` rows created → session issued.
3. **Bot CRUD + 5-cap.** Bot model + `bots` table (in `0002`); service + routes
   (create/list/get/delete), owner-scoped, cap enforced. **Checkpoint:** integration tests via
   overridden `current_active_user`: create/list/delete happy paths; 6th create → 409;
   cross-user access → 404/403.
4. **API keys (generate/rotate, hashed, show-once).** `bots/keys.py` (per D-k); create returns
   plaintext **once**; `POST /api/bots/{id}/rotate-key`; `PostgresBotAuthenticator`.
   **Checkpoint:** integration: create reveals key once; GET never returns plaintext; rotate →
   old `key_hash` gone + new authenticates; `authenticate()` maps token → Bot.
5. **WS handshake real auth + newest-wins.** Inject `BotAuthenticator` + `SessionRegistry` via
   `create_app`; replace the dev-token check; `Session` carries the real `BotInfo`; newest-wins
   replace + rotation evict. Teach `fake_client.py` to send a real key; unit tests inject
   `FakeAuthenticator`. **Checkpoint:** unit WS-seam — valid key → welcome w/ real identity, bad
   key → UNAUTHORIZED close, 2nd handshake evicts 1st socket. Integration — a real DB key
   authenticates a live game end-to-end.
6. **games FK migration + finalizer + house-bot seed.** `0002` adds `white_bot_id`/`black_bot_id`
   (+ SET NULL) and seeds `bot_house_random`; finalizer writes the FKs (D-f name columns kept).
   **Checkpoint:** integration finalize writes both FKs; delete-bot → game row survives with FK
   NULL; updated V1 finalize test green.
7. **Docs + cleanup.** Update CLAUDE.md build-status (V2 ✅), slices.md V2 breadboard, this plan's
   status → done; ruff clean; full gate green; finalize the PR. *(The frontend sub-step is
   dropped — D-j: REST + OAuth only; `npm run check` still runs in the gate but the UI is untouched.)*

## Tests (at the seams — mirrors V1's layering)
- **Unit (`tests/unit/`, no infra):** WS handshake with a `FakeAuthenticator` — real-key welcome
  identity, bad/missing-key UNAUTHORIZED, newest-wins socket eviction, rotation-evicts-live.
  `bots/keys.py` pure-function tests (generate → hash → verify; prefix shape; rotation changes hash).
- **Integration (`tests/integration/`, testcontainers Postgres):** OAuth callback (stubbed
  provider, D-i) → user rows; bot CRUD + 5-cap + owner scoping; key create-once / GET-never /
  rotate-invalidates; `PostgresBotAuthenticator` round-trip; finalizer writes bot FKs; delete-bot
  FK SET NULL.
- **Seam reuse:** extend `tests/support/fake_client.py` (`connect(token=…)` already exists) so the
  token is a real `crbk_` key; add a helper to register a bot+key against an injected authenticator.

## Out of scope (pinned to the slice that proves it)
Elo pools / TTL / same-owner exclusion / anti-rematch → V3 · reconnect-resume (`welcome.active_game`)
/ `ply`-idempotency / heartbeat / illegal-move forfeit → V4 · resign/draw/auto-draw/real-Elo → V5 ·
dashboard/lobby/catch-up/replay/bot-management-UI (unless D-j=B) → V6 · packaged SDK/UCI → V7 ·
rate limits & griefing cooldowns (ADR-0019 H2/H3, need a counter home) → V-later · 5+0 pool → V3.

## Open items (flag, don't block)
- **O-1 (D-f):** kickoff says FKs *replace* `white_name`/`black_name`; this plan **keeps** them as a
  history snapshot so bot-deletion doesn't erase past-game readability. Confirm keep-vs-drop.
- **O-2:** GitHub OAuth needs a registered OAuth app + callback URL for a *real* end-to-end login;
  tests stub the provider (D-i), so this only blocks a live browser demo, not CI. Provide
  `ER_GITHUB_CLIENT_ID`/`_SECRET` (and callback) at demo time.
- **O-3:** integration fixture uses `create_all`, not real migrations — `0002` correctness in CI is
  covered by a dedicated migration test (sub-step 1) rather than the shared fixture. Switching the
  fixture to migrations remains a WORKFLOW-ADOPTION follow-up.
- **O-4 (D-k):** HMAC-SHA256(pepper) deviates from ADR-0014's literal "salted (per-row)" wording —
  a per-row salt is incompatible with the O(1) key→bot lookup the handshake needs. HMAC with a
  server-side pepper honors the ADR's *intent* (hashed at rest; a DB leak alone yields no usable
  credentials). Amend ADR-0014 to record this when V2 lands.
