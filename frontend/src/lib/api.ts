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
