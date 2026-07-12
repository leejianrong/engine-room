<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		fetchBotHistory,
		fetchGame,
		toPgn,
		fmtResult,
		fmtTimeControl,
		type BotHistory,
		type BotGameEntry
	} from '$lib/api';

	let history = $state<BotHistory | null>(null);
	let error = $state('');
	let loaded = $state(false);
	let downloading = $state('');

	const botId = $derived(page.params.id ?? '');

	async function load() {
		try {
			history = await fetchBotHistory(botId);
			error = '';
		} catch (e) {
			error = String(e);
		} finally {
			loaded = true;
		}
	}

	onMount(load);

	// Rating trajectory (oldest → newest): each game carries this bot's own
	// {before, after}. Prepend the earliest `before` so n games plot n+1 points.
	const ratingSeries = $derived.by(() => {
		if (!history) return [] as number[];
		const chrono = history.games.filter((g) => g.rating).slice().reverse();
		if (!chrono.length) return [];
		const pts = [chrono[0].rating!.before];
		for (const g of chrono) pts.push(g.rating!.after);
		return pts;
	});

	// Sparkline geometry: normalise the series into a 160×40 viewBox path.
	const SPARK_W = 160;
	const SPARK_H = 40;
	const sparkPath = $derived.by(() => {
		const s = ratingSeries;
		if (s.length < 2) return '';
		const min = Math.min(...s);
		const max = Math.max(...s);
		const span = max - min || 1;
		const dx = SPARK_W / (s.length - 1);
		return s
			.map((v, i) => {
				const x = i * dx;
				const y = SPARK_H - 4 - ((v - min) / span) * (SPARK_H - 8);
				return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	});
	const sparkTrend = $derived(
		ratingSeries.length >= 2 ? ratingSeries[ratingSeries.length - 1] - ratingSeries[0] : 0
	);

	function watchHref(g: BotGameEntry): string {
		return `/watch?game=${g.game_id}&finished=1`;
	}

	function resultClass(r: BotGameEntry['result']): string {
		return r; // 'win' | 'loss' | 'draw' — styled below
	}

	function ratingDelta(g: BotGameEntry): string {
		if (!g.rating) return '';
		const d = g.rating.after - g.rating.before;
		return `${d >= 0 ? '+' : ''}${d}`;
	}

	function fmtDate(iso: string | null): string {
		if (!iso) return '';
		const d = new Date(iso);
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
	}

	// Per-game PGN download — the detail endpoint exposes SAN moves, which we
	// render to a minimal PGN client-side (no raw-PGN API field).
	async function downloadPgn(g: BotGameEntry) {
		downloading = g.game_id;
		try {
			const view = await fetchGame(g.game_id);
			const pgn = toPgn(view);
			const blob = new Blob([pgn], { type: 'application/x-chess-pgn' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `engine-room-${g.game_id.slice(0, 8)}.pgn`;
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = `PGN download failed: ${e}`;
		} finally {
			downloading = '';
		}
	}
</script>

<svelte:head>
	<title>Engine Room — {history?.bot.name ?? 'Bot'}</title>
</svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>{history?.bot.name ?? 'Bot profile'}</h1>
			<nav>
				<a href="/leaderboard">← Leaderboard</a>
				<a href="/">Lobby</a>
			</nav>
		</div>
		<p class="tag">Finished-game history — read-only.</p>
	</header>

	{#if error}
		<p class="error">Couldn’t load this bot: {error}</p>
	{/if}

	{#if history}
		<section class="overview">
			<div class="stats">
				<div class="stat">
					<span class="label">Rating</span>
					<span class="value rating">{history.summary.rating}</span>
				</div>
				<div class="stat">
					<span class="label">Record (W/L/D)</span>
					<span class="value record">
						<span class="w">{history.summary.wins}</span>
						<span class="sep">/</span>
						<span class="l">{history.summary.losses}</span>
						<span class="sep">/</span>
						<span class="d">{history.summary.draws}</span>
					</span>
				</div>
				<div class="stat">
					<span class="label">Games</span>
					<span class="value">{history.summary.games_played}</span>
				</div>
			</div>

			<div class="spark">
				<span class="label">Rating history</span>
				{#if sparkPath}
					<svg viewBox="0 0 {SPARK_W} {SPARK_H}" width={SPARK_W} height={SPARK_H} class="sparkline">
						<path d={sparkPath} class:up={sparkTrend >= 0} class:down={sparkTrend < 0} />
					</svg>
					<span class="trend" class:up={sparkTrend >= 0}>
						{sparkTrend >= 0 ? '+' : ''}{sparkTrend}
					</span>
				{:else}
					<span class="empty">Not enough rated games yet.</span>
				{/if}
			</div>
		</section>

		<section>
			<h2>Recent games <span class="count">{history.games.length}</span></h2>
			{#if history.games.length}
				<table>
					<thead>
						<tr>
							<th>Result</th>
							<th>Opponent</th>
							<th class="center">Color</th>
							<th class="num">Rating</th>
							<th>Termination</th>
							<th class="num">Date</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each history.games as g (g.game_id)}
							<tr>
								<td>
									<a class="res {resultClass(g.result)}" href={watchHref(g)}>{g.result}</a>
								</td>
								<td>
									{#if g.opponent.bot_id}
										<a class="opp" href={`/bots/${g.opponent.bot_id}`}>{g.opponent.name}</a>
									{:else}
										<span class="opp">{g.opponent.name}</span>
									{/if}
									{#if g.opponent.rating != null}<span class="oppr">{g.opponent.rating}</span>{/if}
								</td>
								<td class="center">{g.color}</td>
								<td class="num">
									{#if g.rating}
										{g.rating.after}
										<span class="delta" class:up={g.rating.after - g.rating.before >= 0}
											>{ratingDelta(g)}</span
										>
									{:else}
										—
									{/if}
								</td>
								<td class="term">{g.termination?.replace(/_/g, ' ') ?? ''}</td>
								<td class="num date">{fmtDate(g.finished_at)}</td>
								<td class="center">
									<button
										class="pgn"
										title="Download PGN"
										disabled={downloading === g.game_id}
										onclick={() => downloadPgn(g)}
									>
										{downloading === g.game_id ? '…' : 'PGN'}
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="empty">No finished games yet.</p>
			{/if}
		</section>
	{:else if !loaded}
		<p class="empty">Loading…</p>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 52rem;
		margin: 2rem auto;
		padding: 0 1rem;
	}
	.titlebar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
	}
	header h1 {
		margin: 0;
	}
	nav {
		display: flex;
		gap: 1.1rem;
	}
	nav a {
		color: #779556;
		text-decoration: none;
		white-space: nowrap;
	}
	.tag {
		color: #888;
		margin: 0.2rem 0 1.5rem;
	}
	.overview {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-end;
		gap: 1.5rem;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 1rem 1.2rem;
		margin-bottom: 2rem;
	}
	.stats {
		display: flex;
		gap: 2rem;
	}
	.stat {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.label {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
	}
	.value {
		font-size: 1.5rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.value.rating {
		color: #779556;
	}
	.record .w {
		color: #4a8;
	}
	.record .l {
		color: #b33;
	}
	.record .d {
		color: #888;
	}
	.record .sep {
		color: #ccc;
		font-weight: 400;
	}
	.spark {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		align-items: flex-start;
	}
	.sparkline {
		display: block;
	}
	.sparkline path {
		fill: none;
		stroke: #779556;
		stroke-width: 1.5;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.sparkline path.down {
		stroke: #b33;
	}
	.trend {
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
		color: #b33;
	}
	.trend.up {
		color: #4a8;
	}
	h2 {
		font-size: 1rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		border-bottom: 1px solid var(--line, #e2e2e2);
		padding-bottom: 0.3rem;
	}
	.count {
		color: #779556;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		text-align: left;
		border-bottom: 1px solid var(--line, #e2e2e2);
		padding: 0.4rem 0.5rem;
	}
	td {
		padding: 0.45rem 0.5rem;
		border-bottom: 1px solid var(--line, #eee);
	}
	th.num,
	td.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	th.center,
	td.center {
		text-align: center;
	}
	.res {
		text-transform: capitalize;
		font-weight: 600;
		text-decoration: none;
	}
	.res.win {
		color: #4a8;
	}
	.res.loss {
		color: #b33;
	}
	.res.draw {
		color: #888;
	}
	.res:hover {
		text-decoration: underline;
	}
	.opp {
		color: inherit;
		text-decoration: none;
		font-weight: 600;
	}
	a.opp:hover {
		color: #779556;
		text-decoration: underline;
	}
	.oppr {
		color: #888;
		margin-left: 0.35rem;
		font-variant-numeric: tabular-nums;
		font-size: 0.85rem;
	}
	.delta {
		color: #b33;
		margin-left: 0.3rem;
		font-size: 0.8rem;
	}
	.delta.up {
		color: #4a8;
	}
	.term {
		color: #888;
		text-transform: capitalize;
	}
	.date {
		color: #888;
		font-size: 0.85rem;
	}
	.pgn {
		font: inherit;
		font-size: 0.78rem;
		padding: 0.15rem 0.5rem;
		border: 1px solid var(--line, #ccc);
		border-radius: 5px;
		background: var(--btn, #fff);
		color: inherit;
		cursor: pointer;
	}
	.pgn:hover:not(:disabled) {
		border-color: #779556;
		color: #779556;
	}
	.pgn:disabled {
		opacity: 0.5;
		cursor: default;
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
		.overview,
		th {
			--line: #333;
		}
		td {
			--line: #2a2a2a;
		}
		.record .sep {
			color: #444;
		}
		.pgn {
			--line: #333;
			--btn: #1a1a1a;
		}
	}
</style>
