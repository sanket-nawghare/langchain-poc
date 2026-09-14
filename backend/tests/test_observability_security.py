"""Phase 6 observability and HTTP boundary tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.observability import (
    RequestObservabilityMiddleware,
    SecurityHeadersMiddleware,
    WorkflowRateLimitMiddleware,
    metrics_registry,
)
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_health_responses_include_security_and_request_headers(
    client: AsyncClient,
) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


@pytest.mark.anyio
async def test_metrics_endpoint_reports_requests_without_payload_content(
    client: AsyncClient,
) -> None:
    before = metrics_registry.snapshot()["request_count"]

    await client.get("/health/live")
    response = await client.get("/health/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_count"] > before
    assert payload["route_counts"]["/health/live"] >= 1
    assert "patient_id" not in response.text
    assert "query" not in response.text


@pytest.mark.anyio
async def test_oversized_body_is_rejected_before_workflow_execution(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/workflows",
        content=b"x" * 20_000,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"


@pytest.mark.anyio
async def test_workflow_rate_limit_returns_safe_error() -> None:
    limited_app = FastAPI()

    @limited_app.post("/api/v1/workflows")
    async def create() -> dict[str, str]:
        return {"status": "accepted"}

    limited_app.add_middleware(SecurityHeadersMiddleware)
    limited_app.add_middleware(RequestObservabilityMiddleware)
    limited_app.add_middleware(WorkflowRateLimitMiddleware, requests_per_minute=1)

    async with AsyncClient(
        transport=ASGITransport(app=limited_app),
        base_url="http://test",
    ) as test_client:
        first = await test_client.post("/api/v1/workflows", json={"ok": True})
        second = await test_client.post("/api/v1/workflows", json={"ok": True})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert second.json()["error"]["code"] == "rate_limited"
    assert "ok" not in second.text
