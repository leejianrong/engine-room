"""KAN-63 (first slice): structured JSON logging, request-id middleware, /metrics.

Fast, infra-free: an in-process ASGI client + direct exercise of the formatter.
"""

import json
import logging

import httpx

from engine_room.app import create_app
from engine_room.observability import (
    CONTENT_TYPE_LATEST,
    JsonFormatter,
    request_id_var,
)


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# --- /metrics ---------------------------------------------------------------


async def test_metrics_endpoint_returns_prometheus_exposition():
    app = create_app()
    async with await _client(app) as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == CONTENT_TYPE_LATEST
    # Our app metrics are present in the text exposition.
    body = resp.text
    assert "er_http_requests_total" in body
    assert "er_games_active" in body
    assert "er_games_started_total" in body
    assert "er_games_finished_total" in body


async def test_metrics_counts_the_request_it_served():
    app = create_app()
    async with await _client(app) as client:
        await client.get("/health")
        resp = await client.get("/metrics")
    # The /health GET (200) is reflected in the counter series.
    assert 'er_http_requests_total{method="GET",status="200"}' in resp.text


# --- request-id middleware --------------------------------------------------


async def test_request_id_header_is_generated_when_absent():
    app = create_app()
    async with await _client(app) as client:
        resp = await client.get("/health")
    rid = resp.headers.get("x-request-id")
    assert rid is not None
    assert rid.startswith("req_")


async def test_inbound_request_id_is_echoed():
    app = create_app()
    async with await _client(app) as client:
        resp = await client.get("/health", headers={"X-Request-ID": "req_deadbeef0001"})
    assert resp.headers.get("x-request-id") == "req_deadbeef0001"


# --- JSON formatter ---------------------------------------------------------


def test_json_formatter_emits_parseable_json_with_context_and_extra():
    token = request_id_var.set("req_abc123")
    try:
        record = logging.LogRecord(
            name="engine_room.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="launching game",
            args=(),
            exc_info=None,
        )
        record.game_id = "game_feedface"  # a caller-supplied extra=
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)

    parsed = json.loads(line)  # one parseable JSON object per line
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "engine_room.test"
    assert parsed["msg"] == "launching game"
    assert parsed["request_id"] == "req_abc123"
    assert parsed["game_id"] == "game_feedface"
    assert "ts" in parsed


def test_json_formatter_includes_exception_text():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="engine_room.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="it failed",
            args=(),
            exc_info=logging.sys.exc_info(),
        )
    parsed = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in parsed["exc"]
