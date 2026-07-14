<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		fetchTournament,
		startTournament,
		fmtTimeControl,
		type TournamentDetail,
		type TournamentGame
	} from '$lib/api';
	import { ApiError, fetchMe } from '$lib/auth';

	let t = $state<TournamentDetail | null>(null);
	let error = $state('');
	let loaded = $state(false);
	let userId = $state<string | null>(null);
	let starting = $state(false);

	const tournamentId = $derived(page.params.id ?? '');

	// bot_id → display name, from the standings (covers every entrant).
	const nameOf = $derived(
		new Map((t?.standings ?? []).map((s) => [s.bot_id, s.name ?? s.bot_id]))
	);

	// The schedule is a true sequence, so group the flat games list by round.
	const rounds = $derived.by(() => {
		const byRound = new Map<number, TournamentGame[]>();
		for (const g of t?.games ?? []) {
			(byRound.get(g.round) ?? byRound.set(g.round, []).get(g.round)!).push(g);
		}
		return [...byRound.entries()].sort((a, b) => a[0] - b[0]);
	});

	// Owner sees the Start control only while the event is still pending.
	const isOwner = $derived(!!userId && !!t?.created_by && userId === t.created_by);
	const canStart = $derived(isOwner && t?.status === 'pending');

	async function load() {
		try {
			t = await fetchTournament(tournamentId);
			error = '';
		} catch (e) {
			error = e instanceof ApiError && e.status === 404 ? 'No such tournament.' : String(e);
		} finally {
			loaded = true;
		}
	}

	async function loadUser() {
		try {
			userId = (await fetchMe()).id;
		} catch {
			userId = null; // anonymous — fine, just no owner controls
		}
	}

	async function onStart() {
		if (!t || starting) return;
		starting = true;
		error = '';
		try {
			await startTournament(t.id);
			await load();
		} catch (e) {
			if (e instanceof ApiError && e.status === 403) error = 'This isn’t your tournament to start.';
			else if (e instanceof ApiError && e.status === 409) error = 'This tournament is no longer pending.';
			else if (e instanceof ApiError && e.status === 401) error = 'Sign in to start a tournament.';
			else error = String(e);
			await load(); // resync in case someone else advanced it
		} finally {
			starting = false;
		}
	}

	function fmtDate(iso: string | null): string {
		if (!iso) return '';
		return new Date(iso).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	// The result column, from White's side: a played/forfeit result is a score,
	// a bye/void is a word, an unplayed pairing is a plain "vs".
	function score(g: TournamentGame): string {
		switch (g.result) {
			case 'white_wins':
				return '1 – 0';
			case 'black_wins':
				return '0 – 1';
			case 'draw':
				return '½ – ½';
			case 'bye':
				return 'bye';
			case 'void':
				return 'void';
			default:
				return 'vs';
		}
	}

	function winner(g: TournamentGame): 'white' | 'black' | null {
		if (g.result === 'white_wins') return 'white';
		if (g.result === 'black_wins') return 'black';
		return null;
	}

	// A real game was played iff game_id is set — that's the only replay link.
	// bye/void/forfeit resolve without a game row.
	function played(g: TournamentGame): boolean {
		return g.game_id != null;
	}

	function note(g: TournamentGame): string {
		if (g.game_id != null) return '';
		if (g.result === 'bye') return 'odd field';
		if (g.result === 'void') return 'both offline';
		if (g.result === 'white_wins' || g.result === 'black_wins') return 'forfeit';
		return 'not started';
	}

	onMount(() => {
		load();
		loadUser();
	});
</script>

<svelte:head><title>Engine Room — {t?.name ?? 'Tournament'}</title></svelte:head>

<main>
	<header>
		<a class="crumb" href="/tournaments">← All tournaments</a>
		<div class="titlebar">
			<h1>
				{t?.name ?? 'Tournament'}
				{#if t}<span class="status {t.status}">{t.status}</span>{/if}
			</h1>
		</div>
		{#if t}
			<p class="tag">
				round robin · {fmtTimeControl(t.time_control)} · {t.target_size} entrants
				{#if t.started_at}· started {fmtDate(t.started_at)}{/if}
			</p>
		{/if}
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if canStart}
		<section class="owner-bar">
			<span class="lead">
				This tournament is pending — {t?.standings.length ?? 0} of {t?.target_size} entrants.
			</span>
			<button class="btn primary" onclick={onStart} disabled={starting}>
				{starting ? 'Starting…' : 'Start now →'}
			</button>
		</section>
	{/if}

	{#if t}
		<section>
			<h2>Standings</h2>
			{#if t.standings.length}
				<table>
					<thead>
						<tr>
							<th class="rank">#</th>
							<th>Bot</th>
							<th class="num">Seed</th>
							<th class="num">Score</th>
						</tr>
					</thead>
					<tbody>
						{#each t.standings as s (s.bot_id)}
							<tr>
								<td class="rank">{s.rank}</td>
								<td><a class="name" href={`/bots/${s.bot_id}`}>{s.name ?? s.bot_id}</a></td>
								<td class="num">{s.seed}</td>
								<td class="num pts">{s.score}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="empty">No entrants yet — bots join by seeking with this tournament’s id.</p>
			{/if}
		</section>

		<section>
			<h2>Schedule &amp; results</h2>
			{#if rounds.length}
				{#each rounds as [roundNo, games] (roundNo)}
					<div class="round-head">Round {roundNo + 1}</div>
					{#each games as g (g.round + '-' + (g.white_bot_id ?? 'x') + '-' + (g.black_bot_id ?? 'x'))}
						<div class="pairing">
							<span class="side" class:win={winner(g) === 'white'}>
								{g.white_bot_id ? (nameOf.get(g.white_bot_id) ?? g.white_bot_id) : '—'}
							</span>
							<span class="vresult">{score(g)}</span>
							<span class="side right" class:win={winner(g) === 'black'}>
								{g.black_bot_id ? (nameOf.get(g.black_bot_id) ?? g.black_bot_id) : '—'}
							</span>
							{#if note(g)}<span class="term">{note(g)}</span>{/if}
							{#if played(g)}
								<a class="watch-link" href={`/watch?game=${g.game_id}&finished=1`}>Replay →</a>
							{/if}
						</div>
					{/each}
				{/each}
			{:else}
				<p class="empty">The schedule is drawn once the tournament starts.</p>
			{/if}
		</section>
	{:else if !loaded}
		<p class="empty">Loading…</p>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 48rem;
		margin: 2rem auto;
		padding: 0 1rem;
	}
	.crumb {
		color: #779556;
		text-decoration: none;
		font-size: 0.9rem;
	}
	.crumb:hover {
		text-decoration: underline;
	}
	.titlebar {
		margin-top: 0.4rem;
	}
	header h1 {
		margin: 0;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}
	.status {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-radius: 4px;
		padding: 0.1rem 0.45rem;
		border: 1px solid currentColor;
		font-weight: 400;
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
	.tag {
		color: #888;
		margin: 0.3rem 0 1.5rem;
	}
	.owner-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		flex-wrap: wrap;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 0.7rem 0.9rem;
		margin-bottom: 1.5rem;
	}
	.owner-bar .lead {
		color: #888;
		font-size: 0.9rem;
	}
	.btn {
		font: inherit;
		font-size: 0.85rem;
		cursor: pointer;
		color: #779556;
		background: transparent;
		border: 1px solid #779556;
		border-radius: 4px;
		padding: 0.35rem 0.9rem;
		white-space: nowrap;
	}
	.btn.primary {
		background: #779556;
		color: #fff;
	}
	.btn.primary:hover:not(:disabled) {
		background: #67853f;
	}
	.btn:disabled {
		opacity: 0.55;
		cursor: default;
	}
	h2 {
		font-size: 1rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		border-bottom: 1px solid var(--line, #e2e2e2);
		padding-bottom: 0.3rem;
		margin-top: 2rem;
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
		border-bottom: 1px solid var(--rowline, #eee);
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
	.pts {
		color: #779556;
		font-weight: 600;
	}
	.round-head {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
		margin: 1.4rem 0 0.4rem;
	}
	.pairing {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		border-bottom: 1px solid var(--rowline, #eee);
		padding: 0.5rem 0.2rem;
		font-size: 0.92rem;
		flex-wrap: wrap;
	}
	.side {
		min-width: 8rem;
		flex: 1;
	}
	.side.right {
		text-align: right;
	}
	.side.win {
		font-weight: 600;
	}
	.vresult {
		font-variant-numeric: tabular-nums;
		color: #888;
		min-width: 3.5rem;
		text-align: center;
	}
	.term {
		color: #888;
		font-size: 0.8rem;
		font-style: italic;
	}
	.watch-link {
		color: #779556;
		text-decoration: none;
		font-size: 0.82rem;
		white-space: nowrap;
	}
	.watch-link:hover {
		text-decoration: underline;
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
		.owner-bar,
		th,
		h2 {
			--line: #333;
		}
		td,
		.pairing {
			--rowline: #2a2a2a;
		}
	}
</style>
