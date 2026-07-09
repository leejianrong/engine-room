<script lang="ts">
	// A styled 8×8 chess board rendered from a FEN, with rank/file coordinates and
	// a last-move highlight. Unicode piece glyphs, self-contained CSS (no external
	// assets/CDN), theme-aware. Board size is driven by the CSS var --sq.
	type Props = { fen: string; lastMove?: string | null; flip?: boolean };
	let { fen, lastMove = null, flip = false }: Props = $props();

	const GLYPH: Record<string, string> = {
		K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
		k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟'
	};

	type Cell = { piece: string; square: string };

	function fenToCells(f: string): Cell[][] {
		const rows = f.split(' ')[0].split('/');
		return rows.map((row, r) => {
			const cells: Cell[] = [];
			let file = 0;
			for (const ch of row) {
				if (/\d/.test(ch)) {
					for (let i = 0; i < parseInt(ch); i++) {
						cells.push({ piece: '', square: sq(file, r) });
						file++;
					}
				} else {
					cells.push({ piece: ch, square: sq(file, r) });
					file++;
				}
			}
			return cells;
		});
	}

	function sq(file: number, rankRow: number): string {
		return 'abcdefgh'[file] + (8 - rankRow);
	}

	const grid = $derived(fenToCells(fen));
	const oriented = $derived(
		flip ? grid.map((r) => [...r].reverse()).reverse() : grid
	);
	const fromSq = $derived(lastMove ? lastMove.slice(0, 2) : null);
	const toSq = $derived(lastMove ? lastMove.slice(2, 4) : null);

	// Coordinate strips (files along the bottom, ranks along the left).
	const files = $derived(flip ? [...'hgfedcba'] : [...'abcdefgh']);
	const ranks = $derived(flip ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1]);
</script>

<div class="wrap">
	<div class="ranks">
		{#each ranks as r}<span>{r}</span>{/each}
	</div>
	<div class="board" role="img" aria-label="chess position">
		{#each oriented as row, r}
			{#each row as cell, c}
				<div
					class="sq {(r + c) % 2 === 0 ? 'light' : 'dark'}"
					class:hl={cell.square === fromSq || cell.square === toSq}
				>
					{#if cell.piece}
						<span class="pc" class:white={cell.piece === cell.piece.toUpperCase()}
							>{GLYPH[cell.piece]}</span
						>
					{/if}
				</div>
			{/each}
		{/each}
	</div>
	<div class="files">
		{#each files as f}<span>{f}</span>{/each}
	</div>
</div>

<style>
	.wrap {
		--sq: clamp(2rem, 10vw, 3.5rem);
		display: grid;
		grid-template-columns: 1.1rem calc(var(--sq) * 8);
		grid-template-rows: calc(var(--sq) * 8) 1.1rem;
		grid-template-areas: 'ranks board' '. files';
		width: max-content;
	}
	.board {
		grid-area: board;
		display: grid;
		grid-template-columns: repeat(8, var(--sq));
		grid-template-rows: repeat(8, var(--sq));
		border-radius: 4px;
		overflow: hidden;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
	}
	.sq {
		display: flex;
		align-items: center;
		justify-content: center;
		position: relative;
	}
	.light {
		background: #ebecd0;
	}
	.dark {
		background: #779556;
	}
	.hl::after {
		content: '';
		position: absolute;
		inset: 0;
		background: #f6f36988;
		mix-blend-mode: multiply;
	}
	.pc {
		font-size: calc(var(--sq) * 0.78);
		line-height: 1;
		position: relative;
		z-index: 1;
		color: #111;
	}
	.pc.white {
		color: #fff;
		text-shadow:
			0 0 1px #333,
			0 1px 2px rgba(0, 0, 0, 0.5);
	}
	.ranks,
	.files {
		display: flex;
		font-size: 0.7rem;
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.ranks {
		grid-area: ranks;
		flex-direction: column;
		justify-content: space-around;
		align-items: center;
	}
	.files {
		grid-area: files;
		justify-content: space-around;
		align-items: center;
	}
</style>
