<script lang="ts">
	// Static showcase of the SDK's reference bots (KAN-60). No backend endpoint —
	// this catalog is hardcoded so builders have starting points to copy.
	type Bot = {
		name: string;
		level: string;
		tagline: string;
		snippet: string;
	};

	const bots: Bot[] = [
		{
			name: 'RandomBot',
			level: 'Hello-world',
			tagline: 'Plays a uniformly-random legal move. Zero chess knowledge — the smallest bot that plays.',
			snippet: `from engineroom import Bot
import random

class RandomBot(Bot):
    def choose_move(self, board):
        return random.choice(list(board.legal_moves))`
		},
		{
			name: 'GreedyBot',
			level: 'Level 1 — material count',
			tagline: 'Looks one move ahead and grabs the move that maximizes its own material. Takes free pieces and the biggest capture on offer — but walks into recaptures.',
			snippet: `from engineroom import Bot

VALUES = {1: 100, 2: 320, 3: 330, 4: 500, 5: 900, 6: 0}

def material(board):
    s = 0
    for p in board.piece_map().values():
        v = VALUES[p.piece_type]
        s += v if p.color else -v
    return s

class GreedyBot(Bot):
    def choose_move(self, board):
        best, pick = None, None
        for m in board.legal_moves:
            board.push(m)
            score = material(board)
            score = score if not board.turn else -score
            board.pop()
            if best is None or score > best:
                best, pick = score, m
        return pick`
		},
		{
			name: 'MinimaxBot',
			level: 'Level 2 — search',
			tagline: 'Depth-limited minimax with alpha-beta pruning over a material + piece-square evaluation. Non-blundering play that still fits a 3+0 clock.',
			snippet: `from engineroom import Bot
from engineroom import MinimaxBot  # ships ready to run

# Or subclass Bot and drive your own search:
class MyMinimax(Bot):
    def choose_move(self, board):
        return best_move(board, depth=3)  # your alpha-beta`
		},
		{
			name: 'UCIBot (bridge)',
			level: 'Bring your own engine',
			tagline: 'Point an existing UCI engine (e.g. Stockfish) at the platform — client-side, no server changes. Ships as the engineroom-uci console script.',
			snippet: `# Run any UCI engine against the live platform:
ENGINEROOM_KEY=crbk_... engineroom-uci \\
    --engine /usr/bin/stockfish --think-time 0.1`
		}
	];

	const readyToRun = `from engineroom import RandomBot, GreedyBot, MinimaxBot

# Each is a complete bot — just give it a key and run:
GreedyBot(key="crbk_...").run(loop=True)`;
</script>

<svelte:head><title>Engine Room — Bot Gallery</title></svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>Bot Gallery</h1>
			<nav><a href="/">← Lobby</a></nav>
		</div>
		<p class="tag">
			Example bots that ship with the <code>engineroom</code> SDK — copy one as a
			starting point and climb the ladder: random → material → search → your own engine.
		</p>
	</header>

	<section class="quickstart">
		<p>
			Every bot below subclasses <code>Bot</code> and implements one method,
			<code>choose_move(board)</code>, over a
			<a href="https://python-chess.readthedocs.io" target="_blank" rel="noreferrer"
				>python-chess</a
			>
			board. The SDK owns the handshake, matchmaking, reconnects and heartbeats.
		</p>
		<pre><code>{readyToRun}</code></pre>
	</section>

	<ul class="grid">
		{#each bots as b (b.name)}
			<li class="card">
				<div class="head">
					<h2>{b.name}</h2>
					<span class="level">{b.level}</span>
				</div>
				<p class="desc">{b.tagline}</p>
				<pre><code>{b.snippet}</code></pre>
			</li>
		{/each}
	</ul>

	<footer>
		<p>
			Install with <code>pip install engineroom</code>. See the
			<a
				href="https://github.com/leejianrong/engine-room/blob/main/sdk/engineroom/README.md"
				target="_blank"
				rel="noreferrer">SDK README</a
			>
			for the full quickstart.
		</p>
	</footer>
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 50rem;
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
	.quickstart {
		margin-bottom: 1.5rem;
	}
	.quickstart p {
		color: #555;
		margin: 0 0 0.75rem;
	}
	code {
		font-family: ui-monospace, 'SF Mono', Menlo, monospace;
		font-size: 0.85em;
	}
	.tag code,
	.quickstart p code,
	footer code {
		background: var(--chip, #f0f0f0);
		border-radius: 4px;
		padding: 0.05rem 0.3rem;
	}
	pre {
		background: var(--pre, #f6f6f4);
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 0.8rem 1rem;
		overflow-x: auto;
		margin: 0;
	}
	pre code {
		background: none;
		padding: 0;
		font-size: 0.82rem;
		line-height: 1.5;
	}
	.grid {
		list-style: none;
		padding: 0;
		display: grid;
		gap: 1rem;
	}
	.card {
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 10px;
		padding: 1rem 1.1rem;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.card h2 {
		margin: 0;
		font-size: 1.1rem;
	}
	.level {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #779556;
		border: 1px solid #779556;
		border-radius: 4px;
		padding: 0.1rem 0.4rem;
	}
	.desc {
		color: #666;
		margin: 0.5rem 0 0.8rem;
		font-size: 0.92rem;
	}
	footer {
		margin-top: 2rem;
		color: #888;
		font-size: 0.88rem;
	}
	footer a,
	.quickstart a {
		color: #779556;
	}
	:global(:root) {
		color-scheme: light dark;
	}
	@media (prefers-color-scheme: dark) {
		.card,
		pre {
			--line: #333;
		}
		pre {
			--pre: #161616;
		}
		code {
			--chip: #2a2a2a;
		}
		.quickstart p {
			color: #aaa;
		}
		.desc {
			color: #aaa;
		}
	}
</style>
