// Backend API access (cross-origin; CORS-enabled on the server). Override with
// VITE_API_BASE for non-default hosts. One place for the base URL, the typed
// shapes the spectator UI consumes, and the fetch/EventSource helpers (V6).

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8001';

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
