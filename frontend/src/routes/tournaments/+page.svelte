<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchTournaments, fmtTimeControl, type TournamentSummary } from '$lib/api';

	let tournaments = $state<TournamentSummary[]>([]);
	let error = $state('');
	let loaded = $state(false);

	async function load() {
		try {
			tournaments = await fetchTournaments();
			error = '';
		} catch (e) {
			error = String(e);
		} finally {
			loaded = true;
		}
	}

	// Group by lifecycle so running events surface first, then pending, then done.
	const running = $derived(tournaments.filter((t) => t.status === 'running'));
	const pending = $derived(tournaments.filter((t) => t.status === 'pending'));
	const finished = $derived(tournaments.filter((t) => t.status === 'finished'));

	onMount(load);
</script>

<svelte:head><title>Engine Room — Tournaments</title></svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>Tournaments</h1>
			<nav>
				<a href="/">← Lobby</a>
				<a href="/leaderboard">Leaderboard</a>
				<a href="/tournaments/new">+ New</a>
			</nav>
		</div>
		<p class="tag">Round-robin events — click one for standings and games.</p>
	</header>

	{#if error}
		<p class="error">Couldn’t reach the server: {error}</p>
	{/if}

	{#snippet card(t: TournamentSummary)}
		<li>
			<a class="card" class:done={t.status === 'finished'} href={`/tournaments/${t.id}`}>
				<div class="row">
					<span class="tname">{t.name}</span>
					<span class="status {t.status}">{t.status}</span>
				</div>
				<div class="meta">
					<span class="tc">round robin · {fmtTimeControl(t.time_control)}</span>
					<span>{t.entry_count} / {t.target_size} entrants</span>
				</div>
			</a>
		</li>
	{/snippet}

	{#if running.length}
		<section>
			<h2>Live now <span class="count">{running.length}</span></h2>
			<ul class="grid">{#each running as t (t.id)}{@render card(t)}{/each}</ul>
		</section>
	{/if}

	{#if pending.length}
		<section>
			<h2>Filling up <span class="count">{pending.length}</span></h2>
			<ul class="grid">{#each pending as t (t.id)}{@render card(t)}{/each}</ul>
		</section>
	{/if}

	{#if finished.length}
		<section>
			<h2>Finished</h2>
			<ul class="grid">{#each finished as t (t.id)}{@render card(t)}{/each}</ul>
		</section>
	{/if}

	{#if loaded && !tournaments.length}
		<p class="empty">No tournaments yet. <a class="inline" href="/tournaments/new">Create one →</a></p>
	{:else if !loaded}
		<p class="empty">Loading…</p>
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
	.grid {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: 0.75rem;
	}
	.card {
		display: block;
		text-decoration: none;
		color: inherit;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 0.75rem 0.9rem;
		transition:
			border-color 0.15s,
			transform 0.05s;
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
	.tname {
		font-weight: 600;
		font-size: 1.05rem;
	}
	.status {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-radius: 4px;
		padding: 0.05rem 0.4rem;
		border: 1px solid currentColor;
		white-space: nowrap;
	}
	.status.running {
		color: #779556;
	}
	.status.pending {
		color: #888;
	}
	.status.finished {
		color: #b0862a;
	}
	.meta {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
		margin-top: 0.5rem;
		font-size: 0.82rem;
		color: #888;
		flex-wrap: wrap;
	}
	.tc {
		font-variant-numeric: tabular-nums;
	}
	.empty,
	.error {
		color: #888;
	}
	.error {
		color: #b33;
	}
	.inline {
		color: #779556;
		text-decoration: none;
	}
	.inline:hover {
		text-decoration: underline;
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
