import { expect, test } from '@playwright/test';

// The V6 demo path (ADR-0023 end-to-end smoke): an anonymous visitor opens the
// dashboard, sees the live lobby (kept non-empty by the ambient house bots),
// clicks a game, watches from the current state (catch-up snapshot renders the
// board), and replays from move 1. Backend + frontend are started by the
// Playwright webServer config; the DB must be up + migrated.

test('dashboard → watch a live game → replay to move 1', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Engine Room' })).toBeVisible();

	// Ambient house-vs-house games keep the lobby populated — wait for a live card.
	const liveSection = page.locator('section', { hasText: 'Live games' });
	const firstGame = liveSection.locator('a.card').first();
	await expect(firstGame).toBeVisible({ timeout: 30_000 });
	await firstGame.click();

	// Watch page: the board renders 64 squares from the catch-up snapshot.
	await expect(page).toHaveURL(/\/watch\?game=/);
	await expect(page.locator('.sq')).toHaveCount(64);

	// At least one move streams in (catch-up + live tail populate the move list).
	await expect(page.locator('.moves button').first()).toBeVisible({ timeout: 30_000 });

	// Replay from move 1: jump to the start; the ply counter resets to 0/N.
	await page.getByRole('button', { name: 'Start' }).click();
	await expect(page.locator('.ply')).toContainText('0/');

	// Stepping forward one advances to ply 1/N.
	await page.getByRole('button', { name: 'Next' }).click();
	await expect(page.locator('.ply')).toContainText('1/');
});
