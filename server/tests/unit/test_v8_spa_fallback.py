"""V8 (KAN-68): the same-origin SPA is served by the backend WITHOUT shadowing the
API. The catch-all SPA fallback is mounted LAST, so `/api/*`, `/health`, `/docs`, and
`/openapi.json` always win; genuinely unknown paths (SPA client routes like `/bots`,
`/watch`) fall back to `index.html`; real static assets serve as-is. When no build
dir is configured (dev/CI without a frontend build) the app stays API-only and unknown
paths 404 — so tests without a build still work."""

import httpx
import pytest

from engine_room.app import create_app

# A recognisable marker so we can tell "served the SPA" apart from "served an API/doc".
_INDEX_HTML = "<!doctype html><title>SPA</title><div id=app>engine-room-spa</div>"


def _build_dir(tmp_path):
    """A minimal SvelteKit-shaped build: index.html + a hashed asset under _app/."""
    (tmp_path / "index.html").write_text(_INDEX_HTML)
    app_dir = tmp_path / "_app"
    app_dir.mkdir()
    (app_dir / "app.js").write_text("export const x = 1;")
    return str(tmp_path)


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_spa_fallback_does_not_shadow_api_or_docs(tmp_path):
    app = create_app(static_dir=_build_dir(tmp_path))
    async with await _client(app) as client:
        # Root and an unknown (SPA client-route) path both serve index.html.
        root = await client.get("/")
        assert root.status_code == 200
        assert "engine-room-spa" in root.text

        bots = await client.get("/bots")  # a real SvelteKit route, unknown to the server
        assert bots.status_code == 200
        assert "engine-room-spa" in bots.text

        # A real static asset serves its own bytes, not the fallback.
        asset = await client.get("/_app/app.js")
        assert asset.status_code == 200
        assert "export const x" in asset.text

        # API / health / OpenAPI win over the fallback.
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        games = await client.get("/api/games")
        assert games.status_code == 200
        assert "games" in games.json()  # JSON, not index.html

        openapi = await client.get("/openapi.json")
        assert openapi.status_code == 200
        assert openapi.json()["info"]["title"] == "Engine Room"


async def test_no_static_dir_means_api_only(tmp_path):
    # Empty static_dir → no SPA mount; unknown paths 404 (the app still boots).
    app = create_app(static_dir="")
    async with await _client(app) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/bots")).status_code == 404


async def test_missing_index_html_is_not_mounted(tmp_path):
    # A dir without index.html is not a build → no mount (guards a mis-set ER_STATIC_DIR).
    app = create_app(static_dir=str(tmp_path))
    async with await _client(app) as client:
        assert (await client.get("/bots")).status_code == 404


@pytest.mark.parametrize("path", ["/api/games", "/health", "/openapi.json"])
async def test_api_paths_unaffected_without_build(path):
    app = create_app()  # settings.static_dir is empty by default in tests
    async with await _client(app) as client:
        assert (await client.get(path)).status_code == 200
