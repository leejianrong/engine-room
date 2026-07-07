<script lang="ts">
	// V1 scaffold placeholder. The live spectator view (EventSource against the
	// backend SSE endpoint, move list + status) is built in V1 sub-step 7, once
	// the SSE endpoint exists. See docs/shaping/V1-plan.md.
</script>

<svelte:head>
	<title>Engine Room</title>
</svelte:head>

<main>
	<h1>Engine Room</h1>
	<p>Real-time matchmaking &amp; spectating for AI chess bots.</p>
	<p class="muted">Spectator UI scaffold (V1). Live board coming in a later sub-step.</p>
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 40rem;
		margin: 4rem auto;
		padding: 0 1rem;
	}
	h1 {
		margin-bottom: 0.25rem;
	}
	.muted {
		color: #666;
	}
</style>
