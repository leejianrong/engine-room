import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Same-origin in dev (V8): with a relative API_BASE (''), proxy the API paths to the
// backend on :8001 so there's no cross-origin CORS/cookie. The backend mounts
// everything under /api (games, spectate SSE, bot WS, auth, users, bots); /auth +
// /users are proxied too in case anything hits them bare. Applied to BOTH `vite dev`
// (server) and `vite preview` (preview) — the Playwright e2e serves the built SPA via
// `vite preview` on :5174 and needs the same proxy, since prod serves the SPA
// same-origin from the backend (no proxy there).
const apiProxy = {
	'/api': { target: 'http://localhost:8001', changeOrigin: true, ws: true },
	'/auth': { target: 'http://localhost:8001', changeOrigin: true },
	'/users': { target: 'http://localhost:8001', changeOrigin: true }
};

export default defineConfig({
	// Dev server on 5174 (5173 is used by another app); strict so it won't drift.
	server: {
		port: 5174,
		strictPort: true,
		proxy: apiProxy
	},
	// Preview server (built SPA) — same proxy so the e2e is same-origin against :8001.
	preview: {
		port: 5174,
		strictPort: true,
		proxy: apiProxy
	},
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// Static SPA build: the spectator UI is client-side (EventSource/SSE), so we
			// ship static assets with an index.html fallback and disable SSR (+layout.ts).
			adapter: adapter({ fallback: 'index.html' })
		})
	]
});
