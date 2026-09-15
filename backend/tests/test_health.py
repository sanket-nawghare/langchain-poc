"""Smoke tests for the FastAPI application."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.health import readiness_report
from app.main import app
from app.services.readiness import (
    DependencyCheck,
    DependencyState,
    ReadinessReport,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_liveness(client: AsyncClient) -> None:
    response = await client.get(
        "/health/live",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == ("http://localhost:5173")


@pytest.mark.anyio
async def test_readiness(client: AsyncClient) -> None:
    async def ready_dependencies() -> ReadinessReport:
        return ReadinessReport(
            status="ready",
            dependencies=[
                DependencyCheck(
                    name="test",
                    state=DependencyState.AVAILABLE,
                    detail="request_succeeded",
                )
            ],
        )

    app.dependency_overrides[readiness_report] = ready_dependencies
    try:
        response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.anyio
async def test_readiness_returns_503_for_a_failed_dependency(
    client: AsyncClient,
) -> None:
    async def unavailable_dependencies() -> ReadinessReport:
        return ReadinessReport(
            status="not_ready",
            dependencies=[
                DependencyCheck(
                    name="weaviate",
                    state=DependencyState.UNAVAILABLE,
                    detail="request_failed",
                )
            ],
        )

    app.dependency_overrides[readiness_report] = unavailable_dependencies
    try:
        response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
