// Human sign-in (GitHub OAuth → stateless Bearer JWT, ADR-0013 / V2 auth).
//
// The JWT is kept client-side in localStorage and sent as `Authorization:
// Bearer <jwt>` on the bot-management REST calls. This is a static SPA (SSR
// disabled), so every storage access is guarded for the browser.

import { browser } from '$app/environment';
import { API_BASE } from './api';

const TOKEN_KEY = 'er_jwt';

// The current human, as returned by GET /api/users/me (FastAPI-Users UserRead).
export type User = {
	id: string;
	email: string;
	is_active: boolean;
	is_superuser: boolean;
	is_verified: boolean;
};

// Thrown by the API helpers so callers can branch on HTTP status (401 → sign in,
// 409 → bot cap, etc.) rather than string-matching messages.
export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

export function getToken(): string | null {
	return browser ? localStorage.getItem(TOKEN_KEY) : null;
}

export function setToken(token: string): void {
	if (browser) localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
	if (browser) localStorage.removeItem(TOKEN_KEY);
}

// Auth header for REST calls; empty when signed out (server then 401s).
export function authHeaders(): Record<string, string> {
	const t = getToken();
	return t ? { Authorization: `Bearer ${t}` } : {};
}

// Kick off GitHub OAuth: ask the backend for the provider authorize URL, then
// hand the browser to GitHub. After consent, GitHub redirects to the backend
// callback, which issues the session JWT. See README / PR notes on how the JWT
// reaches the SPA (the FastAPI-Users callback currently answers with a JSON
// `{access_token}` body; `captureTokenFromUrl` bridges a redirect variant).
export async function startGitHubLogin(): Promise<void> {
	const resp = await fetch(`${API_BASE}/api/auth/github/authorize`);
	if (!resp.ok) throw new ApiError(resp.status, `authorize failed (${resp.status})`);
	const { authorization_url } = (await resp.json()) as { authorization_url: string };
	window.location.href = authorization_url;
}

// If the JWT came back in the URL (?access_token=… or #access_token=…), persist
// it and scrub the URL. Returns true when a token was captured.
export function captureTokenFromUrl(): boolean {
	if (!browser) return false;
	const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
	const query = new URLSearchParams(window.location.search);
	const token = hash.get('access_token') ?? query.get('access_token');
	if (!token) return false;
	setToken(token);
	history.replaceState(null, '', window.location.pathname);
	return true;
}

// Validate the stored token by resolving the current user. Throws ApiError(401)
// when missing/expired so the UI can drop to the signed-out state.
export async function fetchMe(): Promise<User> {
	const resp = await fetch(`${API_BASE}/api/users/me`, { headers: authHeaders() });
	if (resp.status === 401) throw new ApiError(401, 'not signed in');
	if (!resp.ok) throw new ApiError(resp.status, `me failed (${resp.status})`);
	return (await resp.json()) as User;
}
