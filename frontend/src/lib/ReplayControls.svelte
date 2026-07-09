<script lang="ts">
	// Playback controls over a position list: first / prev / play-pause / next /
	// last + a ply scrubber. `index` is the current position (0 = start, `count` =
	// after the last move) and is $bindable so the parent renders positions[index].
	// `following` (live tip) is $bindable too: any manual scrub turns it off; the
	// LIVE button re-pins it. `canLive` shows the LIVE button only for a game that
	// is still in progress.
	type Props = {
		index: number;
		count: number;
		following?: boolean;
		canLive?: boolean;
	};
	let {
		index = $bindable(0),
		count,
		following = $bindable(false),
		canLive = false
	}: Props = $props();

	let playing = $state(false);

	function go(i: number) {
		index = Math.max(0, Math.min(count, i));
		following = false;
		playing = false;
	}

	function goLive() {
		index = count;
		following = true;
		playing = false;
	}

	// Auto-advance while playing; stop at the end.
	$effect(() => {
		if (!playing) return;
		const id = setInterval(() => {
			if (index >= count) {
				playing = false;
			} else {
				index = index + 1;
			}
		}, 700);
		return () => clearInterval(id);
	});
</script>

<div class="controls">
	<button onclick={() => go(0)} disabled={index === 0} title="Start" aria-label="Start">⏮</button>
	<button onclick={() => go(index - 1)} disabled={index === 0} title="Previous" aria-label="Previous">◀</button>
	<button
		onclick={() => {
			following = false;
			playing = !playing;
		}}
		disabled={index >= count && !playing}
		title="Play/Pause"
		aria-label="Play or pause"
	>
		{playing ? '⏸' : '▶'}
	</button>
	<button onclick={() => go(index + 1)} disabled={index >= count} title="Next" aria-label="Next">▶</button>
	<button onclick={() => go(count)} disabled={index >= count} title="End" aria-label="End">⏭</button>

	<input
		class="scrub"
		type="range"
		min="0"
		max={count}
		bind:value={index}
		oninput={() => {
			following = false;
			playing = false;
		}}
		aria-label="Move scrubber"
	/>

	<span class="ply">{index}/{count}</span>

	{#if canLive}
		<button class="live" class:on={following} onclick={goLive} title="Follow live">● LIVE</button>
	{/if}
</div>

<style>
	.controls {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
	}
	button {
		font: inherit;
		padding: 0.3rem 0.55rem;
		border: 1px solid var(--line, #ccc);
		border-radius: 5px;
		background: var(--btn, #fff);
		color: inherit;
		cursor: pointer;
		line-height: 1;
	}
	button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.scrub {
		flex: 1;
		min-width: 6rem;
	}
	.ply {
		font-variant-numeric: tabular-nums;
		font-size: 0.85rem;
		color: #888;
		min-width: 3rem;
		text-align: right;
	}
	.live {
		color: #b33;
		font-size: 0.8rem;
	}
	.live.on {
		background: #b33;
		color: #fff;
		border-color: #b33;
	}
</style>
