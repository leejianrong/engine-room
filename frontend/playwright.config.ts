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
				ER_AMBIENT_MOVE_DELAY_SECONDS: process.env.ER_AMBIENT_MOVE_DELAY_SECONDS ?? '0.15',
				// KAN-83: deflake sdk.spec's "SDK bot shows on the dashboard". The SDK bot
				// seeks alone in the 3+0 pool and is matched vs the house greeter (ephraim).
				// Two production defaults raced the 45s dashboard assertion on slow CI:
				//   1) the greeter only fires after a 3s solo wait (mm_greeter_solo_wait) —
				//      drop it to 0.5s so the bot is matched promptly; and
				//   2) the greeter game launches with house_move_delay=0 (instant), so a
				//      RandomBot-vs-RandomBot game finishes and is evicted from the registry
				//      in <1s — far shorter than the dashboard's 3s poll, so the *live* card
				//      often never appeared. Pin a 1s house delay so the greeter game stays
				//      live (and watchable) for minutes, reliably caught by the poll.
				ER_MM_GREETER_SOLO_WAIT_SECONDS:
					process.env.ER_MM_GREETER_SOLO_WAIT_SECONDS ?? '0.5',
				ER_MM_TICK_INTERVAL_SECONDS: process.env.ER_MM_TICK_INTERVAL_SECONDS ?? '0.1',
				ER_HOUSE_MOVE_DELAY_SECONDS: process.env.ER_HOUSE_MOVE_DELAY_SECONDS ?? '1'
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
