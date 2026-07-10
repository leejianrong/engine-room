// Human sign-in (GitHub OAuth → HttpOnly cookie session, ADR-0013 / KAN-64).
//
// Since KAN-64 the session is a same-origin HttpOnly cookie (`er_session`): the
// backend serves this SPA (KAN-68), so the browser sends the cookie automatically
// on every API call — no token in JS, no `Authorization` header to plumb. Login
// is a full-page redirect through GitHub that lands back on /bots with the cookie
// set; sign-out POSTs the logout endpoint to clear it.

import { API_BASE } from './api';

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

// Kick off GitHub OAuth: ask the backend for the provider authorize URL, then
// hand the browser to GitHub. After consent, GitHub redirects to the backend
// callback, which sets the session cookie and 302-redirects back to /bots.
export async function startGitHubLogin(): Promise<void> {
	const resp = await fetch(`${API_BASE}/api/auth/github/authorize`);
	if (!resp.ok) throw new ApiError(resp.status, `authorize failed (${resp.status})`);
	const { authorization_url } = (await resp.json()) as { authorization_url: string };
	window.location.href = authorization_url;
}

// Clear the session cookie server-side, then drop to signed-out. Best-effort:
// the cookie backend answers 204 and clears `er_session`.
export async function logout(): Promise<void> {
	await fetch(`${API_BASE}/api/auth/jwt/logout`, { method: 'POST' });
}

// Resolve the current user via the session cookie (sent automatically). Throws
// ApiError(401) when the cookie is missing/expired so the UI drops to signed-out.
export async function fetchMe(): Promise<User> {
	const resp = await fetch(`${API_BASE}/api/users/me`);
	if (resp.status === 401) throw new ApiError(401, 'not signed in');
	if (!resp.ok) throw new ApiError(resp.status, `me failed (${resp.status})`);
	return (await resp.json()) as User;
}
