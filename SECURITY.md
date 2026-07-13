# Security Policy

engine-room is a real-time matchmaking and spectating platform for AI chess bots.
It issues per-bot API keys (`crbk_` keys, stored only as `HMAC-SHA256` hashes),
authenticates humans via GitHub OAuth (a same-origin HttpOnly `er_session` cookie),
and depends on server-side secrets (`ER_AUTH_SECRET`, `ER_API_KEY_PEPPER`). We take
reports about any of these seriously.

## Supported versions

This is a single-branch project without formal releases. Security fixes are applied
to the latest `main`; only the current `main` (and the running deployment built from
it) is supported. There are no back-ports to older commits.

## Reporting a vulnerability

**Please do not open a public GitHub issue, pull request, or discussion for a
security vulnerability** — public disclosure before a fix puts users' bot keys and
sessions at risk.

Report privately through **GitHub's private vulnerability reporting**:

- Go to the repository's **Security** tab → **Report a vulnerability** (this opens a
  private GitHub Security Advisory visible only to you and the maintainer), or
- open the [new advisory form](https://github.com/leejianrong/engine-room/security/advisories/new) directly.

If you cannot use that channel, contact the maintainer **@leejianrong** through
GitHub. There is no dedicated security email address.

Please include enough detail to reproduce: affected component (e.g. WS handshake /
API-key auth, OAuth cookie flow, matchmaking, spectator SSE), steps or a
proof-of-concept, and the potential impact.

## What to expect

This is a small, volunteer-maintained project, so we can't commit to a formal SLA.
As a best effort:

- **Acknowledgement** of your report as soon as the maintainer is able to review it.
- **Triage** — we'll confirm the issue, assess severity, and let you know whether we
  plan to fix it and a rough timeline.
- **Fix & disclosure** — we'll work on a fix privately and coordinate public
  disclosure (and credit, if you'd like it) once a fix has landed.

Please give us a reasonable chance to remediate before any public disclosure. Thank
you for helping keep engine-room and its users safe.
