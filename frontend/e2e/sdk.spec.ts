import { execSync, spawn, type ChildProcess } from 'node:child_process';

import { expect, test } from '@playwright/test';

// V7 end-to-end smoke (ADR-0023, now real): the *engineroom SDK* supplies the
// live game the dashboard watches. Mirrors the hero flow — mint a key, run the
// quickstart RandomBot through the SDK, and watch it show up on the dashboard:
//
//   mint key  →  uv run python random_bot.py  →  matched vs house  →  live lobby card
//
// The backend + frontend are started by the Playwright webServer config (ambient
// bots also run, so we match the SDK bot's card specifically by its name). Runs
// against the same uv + Postgres environment the V6 smoke needs.

const SDK_BOT_NAME = 'local-dev-bot'; // the identity mint_bot provisions
let bot: ChildProcess | undefined;

test.beforeAll(() => {
	// Backend is up (webServer). Mint a real crbk_ key from the same DB/pepper.
	const key = execSync('uv run python -m engine_room.devtools.mint_bot --quiet', {
		cwd: '../server',
		encoding: 'utf8'
	}).trim();

	// Run the quickstart bot through the SDK, pointed at the local backend.
	bot = spawn('uv', ['run', 'python', 'random_bot.py'], {
		cwd: '../sdk/quickstart',
		env: {
			...process.env,
			CHESSROOM_KEY: key,
			CHESSROOM_URL: 'ws://localhost:8001/api/bot/v1'
		},
		stdio: 'ignore',
		detached: true
	});
});

test.afterAll(() => {
	// Kill the detached process group (the bot loops forever).
	if (bot?.pid) {
		try {
			process.kill(-bot.pid);
		} catch {
			/* already gone */
		}
	}
});

test('SDK bot shows on the dashboard and is watchable', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Engine Room' })).toBeVisible();

	// The SDK bot is matched (vs the house greeter) and its card appears.
	const liveSection = page.locator('section', { hasText: 'Live games' });
	const sdkCard = liveSection.locator('a.card', { hasText: SDK_BOT_NAME }).first();
	await expect(sdkCard).toBeVisible({ timeout: 45_000 });

	// Watch it: the board renders from the catch-up snapshot.
	await sdkCard.click();
	await expect(page).toHaveURL(/\/watch\?game=/);
	await expect(page.locator('.sq')).toHaveCount(64);
	await expect(page.locator('.moves button').first()).toBeVisible({ timeout: 30_000 });
});
