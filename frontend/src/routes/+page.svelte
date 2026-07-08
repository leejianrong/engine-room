<script lang="ts">
	import { onMount } from 'svelte';

	// Backend base URL (cross-origin; CORS-enabled on the server).
	// Override with VITE_API_BASE for non-default hosts.
	const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

	type Player = { name: string; rating: number };
	type Move = { ply: number; san: string; uci: string };

	const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

	let gameId = $state('');
	let status = $state('idle');
	let white = $state<Player | null>(null);
	let black = $state<Player | null>(null);
	let fen = $state(START_FEN);
	let moves = $state<Move[]>([]);
	let clocks = $state<{ white_ms: number; black_ms: number } | null>(null);
	let toMove = $state<'white' | 'black'>('white');
	let es: EventSource | null = null;

	const GLYPH: Record<string, string> = {
		K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
		k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟'
	};

	function fenToGrid(f: string): string[][] {
		return f.split(' ')[0].split('/').map((row) => {
			const cells: string[] = [];
			for (const ch of row) {
				if (/\d/.test(ch)) for (let i = 0; i < parseInt(ch); i++) cells.push('');
				else cells.push(ch);
			}
			return cells;
		});
	}

	function fmtClock(ms: number): string {
		const s = Math.max(0, Math.floor(ms / 1000));
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	const grid = $derived(fenToGrid(fen));

	function disconnect() {
		es?.close();
		es = null;
	}

	function connect() {
		if (!gameId) return;
		disconnect();
		moves = [];
		white = black = null;
		fen = START_FEN;
		status = 'connecting…';
		es = new EventSource(`${API_BASE}/api/spectate/${gameId}`);
		es.onopen = () => (status = 'watching');
		es.onmessage = (e) => {
			const ev = JSON.parse(e.data);
			if (ev.type === 'game_start') {
				white = ev.white;
				black = ev.black;
				fen = ev.initial_fen;
				clocks = ev.clocks;
				toMove = 'white';
			} else if (ev.type === 'move') {
				fen = ev.fen;
				clocks = ev.clocks;
				toMove = ev.to_move;
				moves = [...moves, { ply: ev.ply, san: ev.san, uci: ev.uci }];
			} else if (ev.type === 'game_over') {
				fen = ev.final_fen;
				status = `game over — ${ev.result} · ${ev.termination}`;
				disconnect();
			}
		};
		es.onerror = () => {
			if (es && es.readyState === EventSource.CLOSED) status = 'disconnected';
		};
	}

	onMount(() => {
		const g = new URLSearchParams(window.location.search).get('game');
		if (g) {
			gameId = g;
			connect();
		}
		return disconnect;
	});
</script>

<svelte:head><title>Engine Room</title></svelte:head>

<main>
	<h1>Engine Room</h1>

	<form
		class="watch"
		onsubmit={(e) => {
			e.preventDefault();
			connect();
		}}
	>
		<input placeholder="game id (e.g. game_…)" bind:value={gameId} />
		<button type="submit">Watch</button>
		<span class="status">{status}</span>
	</form>

	<div class="game">
		<div class="board">
			{#each grid as row, r}
				{#each row as piece, c}
					<div class="sq {(r + c) % 2 === 0 ? 'light' : 'dark'}">{piece ? GLYPH[piece] : ''}</div>
				{/each}
			{/each}
		</div>

		<aside>
			<div class="players">
				<div class="player" class:active={toMove === 'black'}>
					<strong>{black?.name ?? 'Black'}</strong>
					<span>{black ? black.rating : ''}</span>
					<span class="clock">{clocks ? fmtClock(clocks.black_ms) : ''}</span>
				</div>
				<div class="player" class:active={toMove === 'white'}>
					<strong>{white?.name ?? 'White'}</strong>
					<span>{white ? white.rating : ''}</span>
					<span class="clock">{clocks ? fmtClock(clocks.white_ms) : ''}</span>
				</div>
			</div>

			<ol class="moves">
				{#each moves as m}
					<li>{m.san}</li>
				{/each}
			</ol>
		</aside>
	</div>
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 46rem;
		margin: 2rem auto;
		padding: 0 1rem;
	}
	h1 {
		margin-bottom: 0.5rem;
	}
	.watch {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-bottom: 1rem;
	}
	.watch input {
		flex: 1;
		padding: 0.4rem 0.5rem;
		font: inherit;
	}
	.status {
		color: #666;
		font-size: 0.9rem;
		white-space: nowrap;
	}
	.game {
		display: flex;
		gap: 1.5rem;
		flex-wrap: wrap;
	}
	.board {
		display: grid;
		grid-template-columns: repeat(8, 3rem);
		grid-template-rows: repeat(8, 3rem);
		border: 2px solid #333;
	}
	.sq {
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 2rem;
		line-height: 1;
	}
	.light {
		background: #f0d9b5;
	}
	.dark {
		background: #b58863;
	}
	aside {
		min-width: 12rem;
		flex: 1;
	}
	.player {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
		padding: 0.4rem 0.5rem;
		border-radius: 4px;
	}
	.player.active {
		background: #fff3cd;
	}
	.player .clock {
		margin-left: auto;
		font-variant-numeric: tabular-nums;
	}
	.moves {
		margin-top: 1rem;
		max-height: 18rem;
		overflow-y: auto;
		columns: 2;
		font-variant-numeric: tabular-nums;
	}
</style>
