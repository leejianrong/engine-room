import { defineConfig } from '@playwright/test';

// V6 smoke e2e (ADR-0023 end-to-end). Playwright manages both servers: the
// backend (uvicorn, ambient bots ON so the lobby is never empty) and the built
// frontend preview. The database must already be up + migrated (docker compose
// db locally / a Postgres service in CI) — see `make e2e` and .github/workflows.
const CI = !!process.env.CI;

export default defineConfig({
	testDir: './e2e',
	timeout: 60_000,
	expect: { timeout: 15_000 },
	fullyParallel: false,
	forbidOnly: CI,
	retries: CI ? 1 : 0,
	workers: 1,
	reporter: CI ? [['list'], ['html', { open: 'never' }]] : 'list',
	use: {
		baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5174',
		trace: 'on-first-retry'
	},
	webServer: [
		{
			command:
				'cd ../server && uv run uvicorn engine_room.app:app --port 8001 --log-level warning',
			url: 'http://localhost:8001/health',
			reuseExistingServer: !CI,
			timeout: 60_000,
			env: {
				ER_AMBIENT_GAMES: process.env.ER_AMBIENT_GAMES ?? '2',
				ER_AMBIENT_MOVE_DELAY_SECONDS: process.env.ER_AMBIENT_MOVE_DELAY_SECONDS ?? '0.15'
			}
		},
		{
			command: 'npm run build && npm run preview -- --port 5174 --strictPort',
			url: 'http://localhost:5174',
			reuseExistingServer: !CI,
			timeout: 120_000
		}
	]
});
