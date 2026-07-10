<script lang="ts">
	import { onMount } from 'svelte';
	import { ApiError, fetchMe, logout, startGitHubLogin, type User } from '$lib/auth';
	import {
		createBot,
		deleteBot,
		listBots,
		rotateKey,
		type Bot,
		type BotWithKey
	} from '$lib/api';

	const MAX_BOTS = 5;

	let user = $state<User | null>(null);
	let bots = $state<Bot[]>([]);
	let loading = $state(true);
	let signedOut = $state(false);
	let error = $state('');

	// create form
	let newName = $state('');
	let newDesc = $state('');
	let creating = $state(false);

	// shown-once key modal (create or rotate)
	let revealed = $state<BotWithKey | null>(null);
	let revealKind = $state<'created' | 'rotated'>('created');
	let copied = $state(false);

	const atCap = $derived(bots.length >= MAX_BOTS);

	async function loadBots() {
		bots = await listBots();
	}

	async function load() {
		loading = true;
		error = '';
		try {
			user = await fetchMe();
			await loadBots();
			signedOut = false;
		} catch (e) {
			if (e instanceof ApiError && e.status === 401) {
				signedOut = true;
				user = null;
			} else {
				error = String(e);
			}
		} finally {
			loading = false;
		}
	}

	function handle(e: unknown) {
		if (e instanceof ApiError && e.status === 401) {
			signedOut = true;
			user = null;
		} else if (e instanceof ApiError && e.status === 409) {
			error = `You've reached the ${MAX_BOTS}-bot limit — delete one to add another.`;
		} else {
			error = String(e);
		}
	}

	async function onCreate(e: SubmitEvent) {
		e.preventDefault();
		if (!newName.trim() || creating) return;
		creating = true;
		error = '';
		try {
			const bot = await createBot({ name: newName.trim(), description: newDesc.trim() });
			revealed = bot;
			revealKind = 'created';
			copied = false;
			newName = '';
			newDesc = '';
			await loadBots();
		} catch (e) {
			handle(e);
		} finally {
			creating = false;
		}
	}

	async function onRotate(bot: Bot) {
		if (!confirm(`Rotate the key for "${bot.name}"?\nThe current key stops working immediately.`))
			return;
		error = '';
		try {
			const updated = await rotateKey(bot.id);
			revealed = updated;
			revealKind = 'rotated';
			copied = false;
			await loadBots();
		} catch (e) {
			handle(e);
		}
	}

	async function onDelete(bot: Bot) {
		if (!confirm(`Delete "${bot.name}"? This can't be undone.`)) return;
		error = '';
		try {
			await deleteBot(bot.id);
			await loadBots();
		} catch (e) {
			handle(e);
		}
	}

	async function copyKey() {
		if (!revealed) return;
		try {
			await navigator.clipboard.writeText(revealed.api_key);
			copied = true;
		} catch {
			copied = false;
		}
	}

	async function signOut() {
		await logout();
		bots = [];
		user = null;
		signedOut = true;
		revealed = null;
	}

	async function signIn() {
		error = '';
		try {
			await startGitHubLogin();
		} catch (e) {
			error = `Couldn't start GitHub sign-in: ${e}`;
		}
	}

	onMount(() => {
		load();
	});
</script>

<svelte:head><title>Engine Room — My Bots</title></svelte:head>

<main>
	<header>
		<div class="titlebar">
			<h1>My Bots</h1>
			<nav>
				<a href="/">← Lobby</a>
				{#if user}
					<button class="link" onclick={signOut}>Sign out</button>
				{/if}
			</nav>
		</div>
		<p class="tag">
			{#if user}
				Signed in as <strong>{user.email}</strong> · manage your chess bots and API keys.
			{:else}
				Sign in to create bots and mint API keys.
			{/if}
		</p>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if loading}
		<p class="empty">Loading…</p>
	{:else if signedOut}
		<section class="signin">
			<p>You're not signed in.</p>
			<button class="primary" onclick={signIn}>Sign in with GitHub</button>
		</section>
	{:else}
		<section>
			<h2>Create a bot</h2>
			{#if atCap}
				<p class="empty">You've reached the {MAX_BOTS}-bot limit. Delete one to add another.</p>
			{:else}
				<form class="create" onsubmit={onCreate}>
					<input
						type="text"
						placeholder="Name (e.g. my-bot)"
						maxlength="64"
						bind:value={newName}
						required
					/>
					<input
						type="text"
						placeholder="Description (optional)"
						maxlength="256"
						bind:value={newDesc}
					/>
					<button class="primary" type="submit" disabled={creating || !newName.trim()}>
						{creating ? 'Creating…' : 'Create bot'}
					</button>
				</form>
			{/if}
		</section>

		<section>
			<h2>Your bots <span class="count">{bots.length}/{MAX_BOTS}</span></h2>
			{#if bots.length}
				<ul class="list">
					{#each bots as bot (bot.id)}
						<li class="card">
							<div class="botmain">
								<div class="row">
									<span class="name">{bot.name}</span>
									<span class="rating">{bot.rating}</span>
								</div>
								{#if bot.description}
									<p class="desc">{bot.description}</p>
								{/if}
								<p class="keyprefix">
									{#if bot.key_prefix}
										key <code>{bot.key_prefix}…</code>
									{:else}
										<em>no key yet</em>
									{/if}
								</p>
							</div>
							<div class="actions">
								<button onclick={() => onRotate(bot)}>Rotate key</button>
								<button class="danger" onclick={() => onDelete(bot)}>Delete</button>
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="empty">No bots yet — create your first one above.</p>
			{/if}
		</section>
	{/if}
</main>

{#if revealed}
	<div
		class="overlay"
		role="button"
		tabindex="0"
		onclick={() => (revealed = null)}
		onkeydown={(e) => e.key === 'Escape' && (revealed = null)}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h3>{revealKind === 'created' ? 'Bot created' : 'Key rotated'} — copy your API key now</h3>
			<p class="warn">
				⚠ This is the only time you'll see this key. It's stored hashed and can't be shown again.
				{#if revealKind === 'rotated'}The previous key is now invalid.{/if}
			</p>
			<div class="keybox">
				<code>{revealed.api_key}</code>
				<button class="primary" onclick={copyKey}>{copied ? 'Copied ✓' : 'Copy'}</button>
			</div>
			<p class="hint">
				Give it to your bot as <code>CHESSROOM_KEY</code> (or the WS
				<code>Authorization: Bearer</code> header).
			</p>
			<button class="link done" onclick={() => (revealed = null)}>I've saved it — close</button>
		</div>
	</div>
{/if}

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
	nav {
		display: flex;
		gap: 1rem;
		align-items: center;
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
		font-variant-numeric: tabular-nums;
	}
	.create {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
	}
	.create input {
		flex: 1 1 12rem;
	}
	input {
		font: inherit;
		padding: 0.5rem 0.6rem;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 6px;
		background: transparent;
		color: inherit;
	}
	button {
		font: inherit;
		cursor: pointer;
		padding: 0.5rem 0.8rem;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 6px;
		background: transparent;
		color: inherit;
		transition: border-color 0.15s;
	}
	button:hover:not(:disabled) {
		border-color: #779556;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	button.primary {
		background: #779556;
		border-color: #779556;
		color: #fff;
	}
	button.primary:hover:not(:disabled) {
		background: #688049;
	}
	button.danger:hover:not(:disabled) {
		border-color: #b33;
		color: #b33;
	}
	button.link {
		border: none;
		background: none;
		color: #779556;
		padding: 0;
		text-decoration: underline;
	}
	.list {
		list-style: none;
		padding: 0;
		display: grid;
		gap: 0.75rem;
	}
	.card {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 0.75rem 0.9rem;
	}
	.botmain {
		min-width: 0;
	}
	.row {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
	}
	.name {
		font-weight: 600;
	}
	.rating {
		color: #888;
		font-variant-numeric: tabular-nums;
	}
	.desc {
		margin: 0.2rem 0;
		color: #888;
		font-size: 0.9rem;
	}
	.keyprefix {
		margin: 0.2rem 0 0;
		font-size: 0.82rem;
		color: #888;
	}
	code {
		font-family: ui-monospace, monospace;
	}
	.actions {
		display: flex;
		gap: 0.5rem;
		flex-shrink: 0;
	}
	.signin {
		text-align: center;
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 8px;
		padding: 2rem 1rem;
	}
	.signin .primary {
		font-size: 1rem;
		padding: 0.6rem 1.2rem;
	}
	.hint {
		color: #888;
		font-size: 0.85rem;
		max-width: 32rem;
		margin: 1rem auto 0.5rem;
	}
	.empty,
	.error {
		color: #888;
	}
	.error {
		color: #b33;
	}
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.55);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1rem;
	}
	.modal {
		background: var(--bg, #fff);
		border: 1px solid var(--line, #e2e2e2);
		border-radius: 10px;
		padding: 1.25rem 1.4rem;
		max-width: 34rem;
		width: 100%;
	}
	.modal h3 {
		margin: 0 0 0.5rem;
	}
	.warn {
		color: #b26a00;
		font-size: 0.9rem;
	}
	.keybox {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
		background: var(--line, #f2f2f2);
		border-radius: 6px;
		padding: 0.5rem;
	}
	.keybox code {
		flex: 1;
		overflow-x: auto;
		white-space: nowrap;
		align-self: center;
		font-size: 0.9rem;
	}
	.done {
		margin-top: 1rem;
		display: inline-block;
	}
	:global(:root) {
		color-scheme: light dark;
	}
	@media (prefers-color-scheme: dark) {
		.card,
		.signin,
		h2 {
			--line: #333;
		}
		.card,
		.signin {
			background: #1a1a1a;
		}
		.modal {
			--bg: #1a1a1a;
			--line: #333;
		}
		.keybox {
			--line: #2a2a2a;
		}
	}
</style>
