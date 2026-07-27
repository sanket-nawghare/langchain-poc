"""Dependency readiness probes with safe failure details."""

import sqlite3
from enum import StrEnum
from pathlib import Path

from httpx import AsyncClient, HTTPError
from pydantic import Field

from app.core.config import Settings
from app.domain.base import ContractModel


class DependencyState(StrEnum):
    """Public dependency readiness states."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class DependencyCheck(ContractModel):
    """One dependency probe result without sensitive exception details."""

    name: str
    state: DependencyState
    detail: str


class ReadinessReport(ContractModel):
    """Aggregate dependency readiness."""

    status: str
    dependencies: list[DependencyCheck] = Field(default_factory=list)


def _check_sqlite(database_url: str) -> DependencyCheck:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return DependencyCheck(
            name="sqlite",
            state=DependencyState.UNAVAILABLE,
            detail="unsupported_database_url",
        )

    database_path = Path(database_url.removeprefix(prefix))
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database_path, timeout=1) as connection:
            connection.execute("SELECT 1").fetchone()
    except (OSError, sqlite3.Error):
        return DependencyCheck(
            name="sqlite",
            state=DependencyState.UNAVAILABLE,
            detail="connection_failed",
        )

    return DependencyCheck(
        name="sqlite",
        state=DependencyState.AVAILABLE,
        detail="connection_succeeded",
    )


async def _check_http(
    client: AsyncClient,
    *,
    name: str,
    url: str,
) -> DependencyCheck:
    try:
        response = await client.get(url)
        response.raise_for_status()
    except HTTPError:
        return DependencyCheck(
            name=name,
            state=DependencyState.UNAVAILABLE,
            detail="request_failed",
        )

    return DependencyCheck(
        name=name,
        state=DependencyState.AVAILABLE,
        detail="request_succeeded",
    )


async def _run_checks(
    settings: Settings,
    client: AsyncClient,
) -> ReadinessReport:
    sqlite_check = _check_sqlite(settings.database_url)
    fhir_check = await _check_http(
        client,
        name="hapi_fhir",
        url=f"{str(settings.fhir_base_url).rstrip('/')}/metadata",
    )
    weaviate_check = await _check_http(
        client,
        name="weaviate",
        url=(f"{str(settings.weaviate_url).rstrip('/')}/v1/.well-known/ready"),
    )
    checks = [sqlite_check, fhir_check, weaviate_check]
    ready = all(check.state == DependencyState.AVAILABLE for check in checks)
    return ReadinessReport(
        status="ready" if ready else "not_ready",
        dependencies=checks,
    )


async def check_dependencies(
    settings: Settings,
    *,
    client: AsyncClient | None = None,
) -> ReadinessReport:
    """Probe SQLite, HAPI FHIR, and Weaviate concurrently."""

    if client is not None:
        return await _run_checks(settings, client)

    async with AsyncClient(
        timeout=settings.dependency_timeout_seconds,
    ) as owned_client:
        return await _run_checks(settings, owned_client)
