// Backend API access. Since V8 (KAN-68) the SPA is served same-origin by the
// backend, so the base URL is empty (relative) by default — every fetch/EventSource
// below hits the same host that served the page. In dev, `npm run dev` on :5174
// proxies /api, /auth, /users to the backend (see vite.config.ts), so relative URLs
// work there too. Override with VITE_API_BASE only to point at a different host.
// One place for the base URL, the typed shapes the spectator UI consumes, and the
// fetch/EventSource helpers (V6).

import { ApiError } from './auth';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export type Player = { name: string; rating: number | null; bot_id?: string | null };
export type TimeControl = { base_seconds: number; increment_seconds: number };
export type MoveEntry = { ply: number; san: string; uci: string; fen: string };
export type Clocks = { white_ms: number; black_ms: number };
export type RatingChange = {
	white: { before: number; after: number };
	black: { before: number; after: number };
};

export type GameState = 'paired' | 'in_progress' | 'finished' | 'aborted';

// A lobby list item (GET /api/games).
export type LobbyEntry = {
	game_id: string;
	state: GameState;
	white: Player;
	black: Player;
	time_control: TimeControl;
	ply: number | null;
	to_move: 'white' | 'black' | null;
	spectators: number; // live SSE subscribers on this game (KAN-54); 0 when finished
	started_at: string | null;
	finished_at: string | null;
	result: string | null;
	termination: string | null;
};

// The full replay/detail view (GET /api/games/{id}).
export type GameView = {
	game_id: string;
	state: GameState;
	white: Player;
	black: Player;
	time_control: TimeControl;
	initial_fen: string;
	moves: MoveEntry[];
	result: string | null;
	termination: string | null;
	final_fen: string | null;
	rating: RatingChange | null;
};

export async function fetchLobby(): Promise<LobbyEntry[]> {
	const resp = await fetch(`${API_BASE}/api/games`);
	if (!resp.ok) throw new Error(`lobby ${resp.status}`);
	return (await resp.json()).games as LobbyEntry[];
}

export async function fetchGame(id: string): Promise<GameView> {
	const resp = await fetch(`${API_BASE}/api/games/${id}`);
	if (!resp.ok) throw new Error(`game ${resp.status}`);
	return (await resp.json()) as GameView;
}

export function spectateSource(id: string): EventSource {
	return new EventSource(`${API_BASE}/api/spectate/${id}`);
}

// A leaderboard row (GET /api/leaderboard) — bots ranked by Elo, read-only.
export type LeaderboardEntry = {
	rank: number;
	bot_id: string;
	name: string;
	rating: number;
	games_played: number;
	is_house: boolean;
};

export async function fetchLeaderboard(limit?: number): Promise<LeaderboardEntry[]> {
	const q = limit != null ? `?limit=${limit}` : '';
	const resp = await fetch(`${API_BASE}/api/leaderboard${q}`);
	if (!resp.ok) throw new Error(`leaderboard ${resp.status}`);
	return (await resp.json()).entries as LeaderboardEntry[];
}

// ── Per-bot profile / game history (GET /api/bots/{bot_id}/games, KAN-53) ──────

// One finished game shaped from the profiled bot's perspective.
export type BotGameEntry = {
	game_id: string;
	color: 'white' | 'black';
	result: 'win' | 'loss' | 'draw';
	opponent: { bot_id: string | null; name: string; rating: number | null };
	rating: { before: number; after: number } | null;
	time_control: TimeControl;
	termination: string | null;
	finished_at: string | null;
};

export type BotHistory = {
	bot: { bot_id: string; name: string };
	summary: {
		wins: number;
		losses: number;
		draws: number;
		games_played: number;
		rating: number;
	};
	games: BotGameEntry[];
};

export async function fetchBotHistory(botId: string, limit?: number): Promise<BotHistory> {
	const q = limit != null ? `?limit=${limit}` : '';
	const resp = await fetch(`${API_BASE}/api/bots/${botId}/games${q}`);
	if (!resp.ok) throw new Error(`bot history ${resp.status}`);
	return (await resp.json()) as BotHistory;
}

// Build a minimal, valid PGN from a finished game's detail view (client-side —
// the API exposes SAN moves, not a raw PGN string). Used for per-game download.
export function toPgn(g: GameView): string {
	const res =
		g.result === 'white_wins'
			? '1-0'
			: g.result === 'black_wins'
				? '0-1'
				: g.result === 'draw'
					? '1/2-1/2'
					: '*';
	const headers = [
		['Event', 'Engine Room'],
		['Site', 'Engine Room'],
		['White', g.white.name],
		['Black', g.black.name],
		['Result', res],
		['Termination', g.termination ?? '?']
	]
		.map(([k, v]) => `[${k} "${String(v).replace(/"/g, "'")}"]`)
		.join('\n');
	let body = '';
	for (let i = 0; i < g.moves.length; i++) {
		if (i % 2 === 0) body += `${i / 2 + 1}. `;
		body += `${g.moves[i].san} `;
	}
	body += res;
	return `${headers}\n\n${body.trim()}\n`;
}

// ── Direct challenge (KAN-55) ─────────────────────────────────────────────────
// Challenges are issued by a *bot* over the WebSocket, not by the browser: a bot
// seeks with `opponent_bot_id` set to the target's id (PROTOCOL §5). The SPA's
// role is to help a user aim their bot — this copies the target bot's id so it can
// be pasted into a targeted seek. Returns true if the clipboard write succeeded.
export async function copyChallengeTarget(botId: string): Promise<boolean> {
	try {
		await navigator.clipboard.writeText(botId);
		return true;
	} catch {
		return false;
	}
}

export function fmtClock(ms: number): string {
	const s = Math.max(0, Math.floor(ms / 1000));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function fmtTimeControl(tc: TimeControl): string {
	return `${Math.round(tc.base_seconds / 60)}+${tc.increment_seconds}`;
}

// ── Bot management (V2 REST, owner-scoped, same-origin cookie session) ──────

// A bot as returned by the API — never the secret key, only the display prefix.
export type Bot = {
	id: string;
	name: string;
	description: string;
	rating: number;
	key_prefix: string | null; // e.g. "crbk_a1b2c3d4"; null until a key exists
	created_at: string;
};

// Returned exactly once at create / rotate: the plaintext key is unrecoverable.
export type BotWithKey = Bot & { api_key: string };

async function botFetch(path: string, init: RequestInit = {}): Promise<Response> {
	// Same-origin: the browser sends the `er_session` cookie automatically, so no
	// auth header is needed here.
	const resp = await fetch(`${API_BASE}/api/bots${path}`, {
		...init,
		headers: {
			'Content-Type': 'application/json',
			...(init.headers ?? {})
		}
	});
	if (!resp.ok) throw new ApiError(resp.status, `bots ${path} → ${resp.status}`);
	return resp;
}

export async function listBots(): Promise<Bot[]> {
	return (await botFetch('')).json() as Promise<Bot[]>;
}

// Create a bot; the response carries the shown-once plaintext key. 409 = cap.
export async function createBot(data: { name: string; description: string }): Promise<BotWithKey> {
	const resp = await botFetch('', { method: 'POST', body: JSON.stringify(data) });
	return resp.json() as Promise<BotWithKey>;
}

// Rotate the key: old key dies instantly, the new one is shown once here.
export async function rotateKey(botId: string): Promise<BotWithKey> {
	const resp = await botFetch(`/${botId}/rotate-key`, { method: 'POST' });
	return resp.json() as Promise<BotWithKey>;
}

export async function deleteBot(botId: string): Promise<void> {
	await botFetch(`/${botId}`, { method: 'DELETE' });
}

// A human-readable outcome line, e.g. "White wins · checkmate".
export function fmtResult(result: string | null, termination: string | null): string {
	if (!result) return '';
	const who =
		result === 'white_wins'
			? 'White wins'
			: result === 'black_wins'
				? 'Black wins'
				: result === 'draw'
					? 'Draw'
					: result === 'aborted'
						? 'Aborted'
						: result;
	return termination ? `${who} · ${termination.replace(/_/g, ' ')}` : who;
}
