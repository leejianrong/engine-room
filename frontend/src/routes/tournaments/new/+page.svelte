<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { createTournament, type TimeControl } from '$lib/api';
	import { ApiError, fetchMe, startGitHubLogin, type User } from '$lib/auth';

	// Blitz/rapid presets → base_seconds / increment_seconds on the wire.
	const TC_PRESETS: { label: string; value: TimeControl }[] = [
		{ label: '3+0 — blitz', value: { base_seconds: 180, increment_seconds: 0 } },
		{ label: '5+0 — blitz', value: { base_seconds: 300, increment_seconds: 0 } },
		{ label: '10+0 — rapid', value: { base_seconds: 600, increment_seconds: 0 } }
	];

	let user = $state<User | null>(null);
	let checked = $state(false);
	let name = $state('');
	let tcIndex = $state(0);
	let targetSize = $state(8);
	let creating = $state(false);
	let error = $state('');

	async function loadUser() {
		try {
			user = await fetchMe();
		} catch (e) {
			if (e instanceof ApiError && e.status === 401) user = null;
			else error = String(e);
		} finally {
			checked = true;
		}
	}

	async function onCreate(e: SubmitEvent) {
		e.preventDefault();
		if (!name.trim() || creating) return;
		creating = true;
		error = '';
		try {
			const t = await createTournament({
				name: name.trim(),
				time_control: TC_PRESETS[tcIndex].value,
				target_size: targetSize
			});
			await goto(`/tournaments/${t.id}`);
		} catch (e) {
			if (e instanceof ApiError && e.status === 401) {
				user = null;
				error = 'Your session expired — sign in again to create a tournament.';
			} else {
				error = String(e);
			}
		} finally {
			creating = false;
		}
	}

	async function signIn() {
		error = '';
		try {
			await startGitHubLogin();
		} catch (e) {
			error = `Couldn’t start GitHub sign-in: ${e}`;
		}
	}

	onMount(loadUser);
</script>

<svelte:head><title>Engine Room — New tournament</title></svelte:head>

<main>
	<header>
		<a class="crumb" href="/tournaments">← All tournaments</a>
		<div class="titlebar"><h1>New tournament</h1></div>
		<p class="tag">
			Create a round-robin. It auto-starts once it fills to the target size — or start it yourself.
		</p>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if !checked}
		<p class="empty">Loading…</p>
	{:else if !user}
		<section class="signin">
			<p>Sign in to create a tournament.</p>
			<button class="btn primary" onclick={signIn}>Sign in with GitHub</button>
		</section>
	{:else}
		<form class="form-card" onsubmit={onCreate}>
			<div class="field">
				<label for="t-name">Name</label>
				<input
					id="t-name"
					type="text"
					maxlength="128"
					placeholder="e.g. Friday Blitz Invitational"
					bind:value={name}
					required
				/>
			</div>
			<div class="field">
				<label for="t-tc">Time control</label>
				<select id="t-tc" bind:value={tcIndex}>
					{#each TC_PRESETS as p, i (i)}
						<option value={i}>{p.label}</option>
					{/each}
				</select>
			</div>
			<div class="field">
				<label for="t-size">Target size</label>
				<input id="t-size" type="number" min="2" max="64" bind:value={targetSize} required />
				<span class="hint">2–64 bots. The event auto-starts when this many enroll.</span>
			</div>
			<div class="form-actions">
				<button class="btn primary" type="submit" disabled={creating || !name.trim()}>
					{creating ? 'Creating…' : 'Create tournament'}
				</button>
				<a class="btn" href="/tournaments">Cancel</a>
			</div>
		</form>
	{/if}
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 40rem;
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
	}
	.tag {
		color: #888;
		margin: 0.3rem 0 1.5rem;
	}
	.form-card {
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 1.2rem 1.3rem;
		max-width: 26rem;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		margin-bottom: 1rem;
	}
	.field label {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #888;
	}
	.field input,
	.field select {
		font: inherit;
		color: inherit;
		background: transparent;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 6px;
		padding: 0.4rem 0.5rem;
	}
	.field .hint {
		font-size: 0.75rem;
		color: #888;
	}
	.form-actions {
		display: flex;
		gap: 0.6rem;
		margin-top: 0.4rem;
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
		text-decoration: none;
		display: inline-block;
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
	.signin p {
		color: #888;
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
		.form-card {
			--line: #333;
		}
		.field input,
		.field select {
			--line: #333;
			background: #111;
		}
	}
</style>
