import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// Dev server on 5174 (5173 is used by another app); strict so it won't drift.
	server: {
		port: 5174,
		strictPort: true
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
