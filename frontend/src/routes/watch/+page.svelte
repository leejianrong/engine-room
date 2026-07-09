<script lang="ts">
	import { onMount } from 'svelte';
	import Board from '$lib/Board.svelte';
	import ReplayControls from '$lib/ReplayControls.svelte';
	import {
		fetchGame,
		spectateSource,
		fmtClock,
		fmtResult,
		fmtTimeControl,
		type Player,
		type MoveEntry,
		type TimeControl,
		type Clocks,
		type RatingChange,
		type GameState
	} from '$lib/api';

	const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

	let gameId = $state('');
	let status = $state('connecting…');
	let white = $state<Player | null>(null);
	let black = $state<Player | null>(null);
	let timeControl = $state<TimeControl | null>(null);
	let initialFen = $state(START_FEN);
	let moves = $state<MoveEntry[]>([]);
	let clocks = $state<Clocks | null>(null);
	let toMove = $state<'white' | 'black'>('white');
	let gameState = $state<GameState>('paired');
	let result = $state<string | null>(null);
	let termination = $state<string | null>(null);
	let rating = $state<RatingChange | null>(null);
	let flip = $state(false);

	// Replay position: 0 = initial, i = after moves[i-1]. `following` pins to the
	// live tip. `es` is the live stream (null for a finished game loaded by REST).
	let index = $state(0);
	let following = $state(true);
	let es: EventSource | null = null;
	let gotData = false;

	const positions = $derived([initialFen, ...moves.map((m) => m.fen)]);
	const fen = $derived(positions[Math.min(index, positions.length - 1)]);
	const lastMove = $derived(index > 0 ? moves[index - 1].uci : null);
	const finished = $derived(gameState === 'finished' || gameState === 'aborted');
	const canLive = $derived(!!es && !finished);

	function delta(side: 'white' | 'black'): string {
		if (!rating) return '';
		const d = rating[side].after - rating[side].before;
		return `${d >= 0 ? '+' : ''}${d}`;
	}

	function applySnapshotOrView(v: {
		white: Player;
		black: Player;
		time_control: TimeControl;
		initial_fen?: string;
		moves: MoveEntry[];
		result?: string | null;
		termination?: string | null;
		rating?: RatingChange | null;
		state?: GameState;
	}) {
		gotData = true;
		white = v.white;
		black = v.black;
		timeControl = v.time_control;
		if (v.initial_fen) initialFen = v.initial_fen;
		moves = v.moves ?? [];
		if (v.state) gameState = v.state;
		if (v.result) {
			result = v.result;
			termination = v.termination ?? null;
			rating = v.rating ?? null;
		}
	}

	function onMove(ev: MoveEntry & { clocks?: Clocks; to_move?: 'white' | 'black' }) {
		// Dedup by ply (catch-up boundary): moves.length is the next expected ply.
		if (ev.ply < moves.length) return;
		if (ev.ply > moves.length) return; // gap — shouldn't happen; ignore
		moves = [...moves, { ply: ev.ply, san: ev.san, uci: ev.uci, fen: ev.fen }];
		if (ev.clocks) clocks = ev.clocks;
		if (ev.to_move) toMove = ev.to_move;
		if (following) index = moves.length;
	}

	async function loadFinished(id: string) {
		try {
			const v = await fetchGame(id);
			applySnapshotOrView(v);
			gameState = v.state;
			index = v.moves.length; // finished → show the final position, scrub back to replay
			following = false;
			status = fmtResult(v.result, v.termination) || 'finished';
		} catch (e) {
			status = `not found: ${e}`;
		}
	}

	function openLive(id: string) {
		es = spectateSource(id);
		es.onmessage = (e) => {
			const ev = JSON.parse(e.data);
			if (ev.type === 'snapshot') {
				applySnapshotOrView(ev);
				clocks = ev.clocks;
				toMove = ev.to_move;
				if (following) index = moves.length;
				status = 'watching';
			} else if (ev.type === 'game_start') {
				if (!gotData) {
					gotData = true;
					white = ev.white;
					black = ev.black;
					timeControl = ev.time_control;
					initialFen = ev.initial_fen;
					clocks = ev.clocks;
					gameState = 'in_progress';
				}
				status = 'watching';
			} else if (ev.type === 'move') {
				onMove(ev);
			} else if (ev.type === 'game_over') {
				result = ev.result;
				termination = ev.termination;
				rating = ev.rating ?? null;
				gameState = ev.result === 'aborted' ? 'aborted' : 'finished';
				status = fmtResult(ev.result, ev.termination);
				es?.close();
			}
		};
		es.onerror = () => {
			// No data yet → the game isn't live in memory; fall back to the durable
			// record (a finished game after a restart, or a bad live guess).
			if (!gotData) {
				es?.close();
				es = null;
				loadFinished(id);
			} else if (es && es.readyState === EventSource.CLOSED && !finished) {
				status = 'disconnected';
			}
		};
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		const id = params.get('game') ?? '';
		gameId = id;
		if (!id) {
			status = 'no game id';
			return;
		}
		if (params.get('finished')) {
			loadFinished(id);
		} else {
			openLive(id);
		}
		return () => es?.close();
	});
</script>

<svelte:head><title>Engine Room — Watch</title></svelte:head>

<main>
	<nav><a href="/">← Lobby</a></nav>

	<div class="game">
		<div class="left">
			<Board {fen} {lastMove} {flip} />
			<div class="under">
				<ReplayControls bind:index bind:following count={moves.length} {canLive} />
				<button class="flip" onclick={() => (flip = !flip)} title="Flip board">⟲ Flip</button>
			</div>
		</div>

		<aside>
			<div class="status">{status}</div>

			{#each [{ p: black, color: 'black' as const }, { p: white, color: 'white' as const }] as seat}
				<div class="player" class:active={toMove === seat.color && !finished}>
					<div class="pname">
						<strong>{seat.p?.name ?? seat.color}</strong>
						<span class="pr">{seat.p?.rating ?? ''}</span>
						{#if rating}<span class="pd" class:up={delta(seat.color).startsWith('+')}
								>{delta(seat.color)}</span
							>{/if}
					</div>
					<span class="clock"
						>{clocks ? fmtClock(seat.color === 'white' ? clocks.white_ms : clocks.black_ms) : ''}</span
					>
				</div>
			{/each}

			{#if timeControl}<div class="tc">{fmtTimeControl(timeControl)} · {gameState}</div>{/if}

			<ol class="moves">
				{#each moves as m, i}
					<li>
						<button class:on={index === i + 1} onclick={() => { index = i + 1; following = false; }}>
							{m.san}
						</button>
					</li>
				{/each}
			</ol>
		</aside>
	</div>
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 56rem;
		margin: 1.5rem auto;
		padding: 0 1rem;
	}
	nav {
		margin-bottom: 1rem;
	}
	nav a {
		color: #779556;
		text-decoration: none;
	}
	.game {
		display: flex;
		gap: 1.5rem;
		flex-wrap: wrap;
		align-items: flex-start;
	}
	.under {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-top: 0.6rem;
	}
	.flip {
		font: inherit;
		padding: 0.3rem 0.55rem;
		border: 1px solid var(--line, #ccc);
		border-radius: 5px;
		background: var(--btn, #fff);
		color: inherit;
		cursor: pointer;
	}
	aside {
		min-width: 13rem;
		flex: 1;
	}
	.status {
		font-size: 0.9rem;
		color: #888;
		margin-bottom: 0.6rem;
		min-height: 1.2em;
	}
	.player {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding: 0.4rem 0.55rem;
		border-radius: 5px;
	}
	.player.active {
		background: #77955622;
	}
	.pname {
		display: flex;
		gap: 0.4rem;
		align-items: baseline;
	}
	.pr {
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.pd {
		font-size: 0.8rem;
		color: #b33;
		font-variant-numeric: tabular-nums;
	}
	.pd.up {
		color: #4a8;
	}
	.clock {
		font-variant-numeric: tabular-nums;
		font-size: 1.1rem;
	}
	.tc {
		color: #888;
		font-size: 0.82rem;
		margin: 0.3rem 0 0.6rem;
	}
	.moves {
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 18rem;
		overflow-y: auto;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.1rem 0.4rem;
		font-variant-numeric: tabular-nums;
	}
	.moves button {
		width: 100%;
		text-align: left;
		font: inherit;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		padding: 0.1rem 0.3rem;
		border-radius: 3px;
	}
	.moves button.on {
		background: #779556;
		color: #fff;
	}
	@media (prefers-color-scheme: dark) {
		.flip {
			--line: #333;
			--btn: #1a1a1a;
		}
	}
	:global(:root) {
		color-scheme: light dark;
	}
</style>
