import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// Dev server on 5174 (5173 is used by another app); strict so it won't drift.
	// Same-origin in dev too (V8): proxy the API paths to the backend on :8001 so a
	// relative API_BASE ('') works and there's no cross-origin CORS/cookie in dev.
	// The backend mounts everything under /api (games, spectate SSE, bot WS, auth,
	// users, bots); /auth + /users are proxied too in case anything hits them bare.
	server: {
		port: 5174,
		strictPort: true,
		proxy: {
			'/api': { target: 'http://localhost:8001', changeOrigin: true, ws: true },
			'/auth': { target: 'http://localhost:8001', changeOrigin: true },
			'/users': { target: 'http://localhost:8001', changeOrigin: true }
		}
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
