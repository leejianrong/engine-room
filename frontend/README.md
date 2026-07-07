# Engine Room — frontend

SvelteKit + Vite spectator UI. Static SPA build (`@sveltejs/adapter-static`, SSR off) —
the UI subscribes to the backend SSE stream at runtime. See
[../docs/shaping/V1-plan.md](../docs/shaping/V1-plan.md) for the current slice; the live
board + lobby are built out in V6.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # -> build/  (static)
npm run check    # svelte-check
```
