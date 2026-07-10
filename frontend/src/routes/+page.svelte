<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchLobby, fmtResult, fmtTimeControl, type LobbyEntry } from '$lib/api';

	let games = $state<LobbyEntry[]>([]);
	let error = $state('');
	let loaded = $state(false);

	const active = $derived(games.filter((g) => g.state === 'paired' || g.state === 'in_progress'));
	const finished = $derived(games.filter((g) => g.state === 'finished' || g.state === 'aborted'));

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
			<nav><a href="/bots">My Bots →</a></nav>
		</div>
		<p class="tag">Live AI chess — click a game to watch.</p>
	</header>

	{#if error}
		<p class="error">Couldn’t reach the server: {error}</p>
	{/if}

	<section>
		<h2>Live games <span class="count">{active.length}</span></h2>
		{#if active.length}
			<ul class="grid">
				{#each active as g (g.game_id)}
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
							</div>
						</a>
					</li>
				{/each}
			</ul>
		{:else if loaded}
			<p class="empty">No live games right now.</p>
		{:else}
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
