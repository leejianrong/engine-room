# Engine Room — frontend

SvelteKit + Vite spectator UI (V6). Static SPA build (`@sveltejs/adapter-static`, SSR off) —
the UI polls `GET /api/games` for the lobby and subscribes to the backend SSE stream while
watching (cross-origin; the backend enables CORS for the dev server).

```bash
npm install
npm run dev      # http://localhost:5174
npm run build    # -> build/  (static)
npm run check    # svelte-check
npm run e2e      # Playwright smokes (needs a built/served stack; see `make e2e`)
```

Backend base URL defaults to `http://localhost:8001`; override with `VITE_API_BASE`.

Routes: `/` is the **dashboard/lobby** (live + recently-finished games); `/watch?game=<id>` is the
**watch** page (catch-up snapshot → live SSE tail, replay controls). Browser e2e lives in `e2e/`.

## Watch a live game

1. Backend + Postgres running (see `../server/README.md`), or just `make dev` from the repo root.
2. Open `http://localhost:5174/` — the lobby lists live games (ambient house-vs-house games keep it
   populated). Start your own with `make sdk-bot` from the repo root.
3. Click a game to watch from the current position and replay it from move 1.
