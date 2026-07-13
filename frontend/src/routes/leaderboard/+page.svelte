<script lang="ts">
	import { onMount } from 'svelte';
	import { copyChallengeTarget, fetchLeaderboard, type LeaderboardEntry } from '$lib/api';

	let entries = $state<LeaderboardEntry[]>([]);
	let error = $state('');
	let loaded = $state(false);
	let copiedId = $state<string | null>(null);

	// Direct challenge (KAN-55): the browser can't open a bot's authenticated
	// WebSocket, so "Challenge" copies the target's id — paste it into your bot's
	// targeted seek (`opponent_bot_id`, PROTOCOL §5) to play this bot directly.
	async function challenge(botId: string) {
		if (await copyChallengeTarget(botId)) {
			copiedId = botId;
			setTimeout(() => (copiedId === botId ? (copiedId = null) : null), 1500);
		}
	}

	async function load() {
		try {
			entries = await fetchLeaderboard();
			error = '';
		} catch (e) {
			error = String(e);
		} finally {
			loaded = true;
		}
	}

	onMount(load);
</script>

<svelte:head><title>Engine Room — Leaderboard</title></svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>Leaderboard</h1>
			<nav><a href="/">← Lobby</a></nav>
		</div>
		<p class="tag">Bots ranked by Elo — updated as games finish.</p>
	</header>

	{#if error}
		<p class="error">Couldn’t reach the server: {error}</p>
	{/if}

	{#if entries.length}
		<table>
			<thead>
				<tr>
					<th class="rank">#</th>
					<th>Bot</th>
					<th class="num">Rating</th>
					<th class="num">Games</th>
					<th class="act"></th>
				</tr>
			</thead>
			<tbody>
				{#each entries as e (e.bot_id)}
					<tr>
						<td class="rank">{e.rank}</td>
						<td>
							<a class="name" href={`/bots/${e.bot_id}`}>{e.name}</a>
							{#if e.is_house}<span class="house">house</span>{/if}
						</td>
						<td class="num rating">{e.rating}</td>
						<td class="num games">{e.games_played}</td>
						<td class="act">
							<button
								class="challenge"
								title="Copy this bot's id to challenge it directly — point your bot at it with a targeted seek (opponent_bot_id)."
								onclick={() => challenge(e.bot_id)}
							>
								{copiedId === e.bot_id ? 'Copied id ✓' : 'Challenge'}
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{:else if loaded}
		<p class="empty">No ranked bots yet — play some games to appear here.</p>
	{:else}
		<p class="empty">Loading…</p>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 40rem;
		margin: 2rem auto;
		padding: 0 1rem;
	}
	.titlebar {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	header h1 {
		margin: 0;
	}
	nav a {
		color: #779556;
		text-decoration: none;
	}
	.tag {
		color: #888;
		margin: 0.2rem 0 1.5rem;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		text-align: left;
		border-bottom: 1px solid var(--line, #e2e2e2);
		padding: 0.4rem 0.6rem;
	}
	td {
		padding: 0.5rem 0.6rem;
		border-bottom: 1px solid var(--line, #eee);
	}
	th.num,
	td.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.rank {
		width: 2.5rem;
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.name {
		font-weight: 600;
		color: inherit;
		text-decoration: none;
	}
	a.name:hover {
		color: #779556;
		text-decoration: underline;
	}
	.house {
		margin-left: 0.4rem;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #779556;
		border: 1px solid #779556;
		border-radius: 4px;
		padding: 0.05rem 0.3rem;
		vertical-align: middle;
	}
	.rating {
		color: #779556;
		font-weight: 600;
	}
	.games {
		color: #888;
	}
	td.act,
	th.act {
		text-align: right;
		width: 7rem;
	}
	.challenge {
		font: inherit;
		font-size: 0.75rem;
		cursor: pointer;
		color: #779556;
		background: transparent;
		border: 1px solid #779556;
		border-radius: 4px;
		padding: 0.15rem 0.5rem;
		white-space: nowrap;
	}
	.challenge:hover {
		background: #77955618;
	}
	.empty,
	.error {
		color: #888;
	}
	.error {
		color: #b33;
	}
	:global(:root) {
		color-scheme: light dark;
	}
	@media (prefers-color-scheme: dark) {
		th {
			--line: #333;
		}
		td {
			--line: #2a2a2a;
		}
	}
</style>
