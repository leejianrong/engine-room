# Engine Room — frontend

SvelteKit + Vite spectator UI. Static SPA build (`@sveltejs/adapter-static`, SSR off) —
the UI subscribes to the backend SSE stream at runtime (cross-origin; the backend
enables CORS for the dev server). See [../docs/shaping/V1-plan.md](../docs/shaping/V1-plan.md)
for the current slice; the live board + lobby are built out in V6.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # -> build/  (static)
npm run check    # svelte-check
```

Backend base URL defaults to `http://localhost:8000`; override with `VITE_API_BASE`.

## Watch a live game (V1 demo)

1. Backend + Postgres running (see `../server/README.md`).
2. Start a bot so a game begins vs the house bot; note its `game_id`.
3. Open `http://localhost:5173/?game=<game_id>` (or paste the id into the input)
   and watch the board update move-by-move.
