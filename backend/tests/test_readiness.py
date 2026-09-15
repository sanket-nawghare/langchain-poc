"""Dependency readiness probe tests."""

from pathlib import Path

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.core.config import Settings
from app.services.readiness import DependencyState, check_dependencies


@pytest.mark.anyio
async def test_all_configured_dependencies_are_available(
    tmp_path: Path,
) -> None:
    def handler(request: Request) -> Response:
        if request.url.path in {
            "/fhir/metadata",
            "/v1/.well-known/ready",
        }:
            return Response(200, request=request)
        return Response(404, request=request)

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        fhir_base_url="http://fhir.test/fhir",
        weaviate_url="http://weaviate.test",
    )
    async with AsyncClient(transport=MockTransport(handler)) as client:
        report = await check_dependencies(settings, client=client)

    assert report.status == "ready"
    assert {dependency.state for dependency in report.dependencies} == {
        DependencyState.AVAILABLE
    }


@pytest.mark.anyio
async def test_failed_http_dependency_is_reported_without_exception_details(
    tmp_path: Path,
) -> None:
    def handler(request: Request) -> Response:
        status_code = 503 if request.url.host == "weaviate.test" else 200
        return Response(status_code, request=request)

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        fhir_base_url="http://fhir.test/fhir",
        weaviate_url="http://weaviate.test",
    )
    async with AsyncClient(transport=MockTransport(handler)) as client:
        report = await check_dependencies(settings, client=client)

    weaviate = next(
        dependency
        for dependency in report.dependencies
        if dependency.name == "weaviate"
    )
    assert report.status == "not_ready"
    assert weaviate.state == DependencyState.UNAVAILABLE
    assert weaviate.detail == "request_failed"
