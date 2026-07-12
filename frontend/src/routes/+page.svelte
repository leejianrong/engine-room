<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchLobby, fmtResult, fmtTimeControl, type LobbyEntry } from '$lib/api';

	let games = $state<LobbyEntry[]>([]);
	let error = $state('');
	let loaded = $state(false);

	// Client-side filters (KAN-54). 'all' = no filter.
	let tcFilter = $state('all');
	let ratingFilter = $state('all');

	const active = $derived(games.filter((g) => g.state === 'paired' || g.state === 'in_progress'));
	const finished = $derived(games.filter((g) => g.state === 'finished' || g.state === 'aborted'));

	// Combined-strength = average of the two seat ratings (unrated → 0).
	function avgRating(g: LobbyEntry): number {
		const w = g.white.rating ?? 0;
		const b = g.black.rating ?? 0;
		return (w + b) / 2;
	}

	type Band = { key: string; label: string; test: (r: number) => boolean };
	const RATING_BANDS: Band[] = [
		{ key: 'lt1200', label: 'Under 1200', test: (r) => r < 1200 },
		{ key: '1200_1599', label: '1200–1599', test: (r) => r >= 1200 && r < 1600 },
		{ key: 'gte1600', label: '1600+', test: (r) => r >= 1600 }
	];

	function ratingBand(g: LobbyEntry): string {
		const r = avgRating(g);
		return RATING_BANDS.find((b) => b.test(r))?.key ?? '';
	}

	// Time-control options come from the live data (e.g. "3+0", "5+0").
	const tcOptions = $derived(
		[...new Set(active.map((g) => fmtTimeControl(g.time_control)))].sort()
	);

	const filteredActive = $derived(
		active.filter(
			(g) =>
				(tcFilter === 'all' || fmtTimeControl(g.time_control) === tcFilter) &&
				(ratingFilter === 'all' || ratingBand(g) === ratingFilter)
		)
	);

	// Featured = most-watched active game, tie-broken by combined rating (KAN-54).
	const featured = $derived(
		filteredActive.length
			? filteredActive.reduce((best, g) =>
					g.spectators !== best.spectators
						? g.spectators > best.spectators
							? g
							: best
						: avgRating(g) > avgRating(best)
							? g
							: best
				)
			: null
	);

	const restActive = $derived(filteredActive.filter((g) => g.game_id !== featured?.game_id));

	async function poll() {
		try {
			games = await fetchLobby();
			error = '';
		} catch (e) {
			error = String(e);
		} finally {
			loaded = true;
		}
	}

	function watchHref(g: LobbyEntry): string {
		const done = g.state === 'finished' || g.state === 'aborted';
		return `/watch?game=${g.game_id}${done ? '&finished=1' : ''}`;
	}

	onMount(() => {
		poll();
		const id = setInterval(poll, 3000);
		return () => clearInterval(id);
	});
</script>

<svelte:head><title>Engine Room — Lobby</title></svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>Engine Room</h1>
			<nav>
				<a href="/leaderboard">Leaderboard</a>
				<a href="/bots">My Bots →</a>
			</nav>
		</div>
		<p class="tag">Live AI chess — click a game to watch.</p>
	</header>

	{#if error}
		<p class="error">Couldn’t reach the server: {error}</p>
	{/if}

	{#if featured}
		<section class="featured-wrap">
			<h2>Featured game</h2>
			<a class="card featured" href={watchHref(featured)}>
				<div class="row">
					<span class="name big" class:turn={featured.to_move === 'white'}>{featured.white.name}</span>
					<span class="rating">{featured.white.rating ?? '—'}</span>
				</div>
				<div class="row">
					<span class="name big" class:turn={featured.to_move === 'black'}>{featured.black.name}</span>
					<span class="rating">{featured.black.rating ?? '—'}</span>
				</div>
				<div class="meta">
					<span class="tc">{fmtTimeControl(featured.time_control)}</span>
					<span class="live">● move {featured.ply ?? 0}</span>
					<span class="watchers">{featured.spectators} watching</span>
				</div>
			</a>
		</section>
	{/if}

	<section>
		<div class="section-head">
			<h2>Live games <span class="count">{filteredActive.length}</span></h2>
			<div class="filters">
				<label>
					Rating
					<select bind:value={ratingFilter}>
						<option value="all">All</option>
						{#each RATING_BANDS as b (b.key)}
							<option value={b.key}>{b.label}</option>
						{/each}
					</select>
				</label>
				<label>
					Time
					<select bind:value={tcFilter}>
						<option value="all">All</option>
						{#each tcOptions as tc (tc)}
							<option value={tc}>{tc}</option>
						{/each}
					</select>
				</label>
			</div>
		</div>
		{#if restActive.length}
			<ul class="grid">
				{#each restActive as g (g.game_id)}
					<li>
						<a class="card" href={watchHref(g)}>
							<div class="row">
								<span class="name" class:turn={g.to_move === 'white'}>{g.white.name}</span>
								<span class="rating">{g.white.rating ?? '—'}</span>
							</div>
							<div class="row">
								<span class="name" class:turn={g.to_move === 'black'}>{g.black.name}</span>
								<span class="rating">{g.black.rating ?? '—'}</span>
							</div>
							<div class="meta">
								<span class="tc">{fmtTimeControl(g.time_control)}</span>
								<span class="live">● move {g.ply ?? 0}</span>
								{#if g.spectators > 0}
									<span class="watchers">{g.spectators} watching</span>
								{/if}
							</div>
						</a>
					</li>
				{/each}
			</ul>
		{:else if !featured && loaded}
			<p class="empty">
				{active.length ? 'No games match your filters.' : 'No live games right now.'}
			</p>
		{:else if !loaded}
			<p class="empty">Loading…</p>
		{/if}
	</section>

	{#if finished.length}
		<section>
			<h2>Recently finished</h2>
			<ul class="grid">
				{#each finished as g (g.game_id)}
					<li>
						<a class="card done" href={watchHref(g)}>
							<div class="row">
								<span class="name">{g.white.name}</span>
								<span class="rating">{g.white.rating ?? '—'}</span>
							</div>
							<div class="row">
								<span class="name">{g.black.name}</span>
								<span class="rating">{g.black.rating ?? '—'}</span>
							</div>
							<div class="meta">
								<span class="tc">{fmtTimeControl(g.time_control)}</span>
								<span class="result">{fmtResult(g.result, g.termination)}</span>
							</div>
						</a>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 60rem;
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
	nav {
		display: flex;
		gap: 1.1rem;
	}
	nav a {
		color: #779556;
		text-decoration: none;
	}
	.tag {
		color: #888;
		margin: 0.2rem 0 1.5rem;
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
	.section-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.section-head h2 {
		flex: 1;
		min-width: 8rem;
	}
	.filters {
		display: flex;
		gap: 0.9rem;
		padding-bottom: 0.3rem;
	}
	.filters label {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.filters select {
		font: inherit;
		font-size: 0.85rem;
		text-transform: none;
		letter-spacing: normal;
		color: inherit;
		background: transparent;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 6px;
		padding: 0.2rem 0.4rem;
	}
	.featured .name.big {
		font-size: 1.15rem;
	}
	.card.featured {
		border-color: #779556;
		border-width: 2px;
		background: color-mix(in srgb, #779556 6%, transparent);
	}
	.watchers {
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.grid {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: 0.75rem;
	}
	.card {
		display: block;
		text-decoration: none;
		color: inherit;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 0.75rem 0.9rem;
		transition: border-color 0.15s, transform 0.05s;
	}
	.card:hover {
		border-color: #779556;
		transform: translateY(-1px);
	}
	.card.done {
		opacity: 0.85;
	}
	.row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 0.5rem;
	}
	.name {
		font-weight: 600;
	}
	.name.turn::before {
		content: '▸ ';
		color: #779556;
	}
	.rating {
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.meta {
		display: flex;
		justify-content: space-between;
		margin-top: 0.5rem;
		font-size: 0.82rem;
		color: #888;
	}
	.tc {
		font-variant-numeric: tabular-nums;
	}
	.live {
		color: #779556;
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
		.card {
			--line: #333;
			background: #1a1a1a;
		}
		h2 {
			--line: #333;
		}
	}
</style>
