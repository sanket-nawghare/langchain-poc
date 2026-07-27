"""Process health endpoints."""

from typing import Literal, TypedDict

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(TypedDict):
    """Response returned by foundation health checks."""

    status: Literal["ok"]


@router.get("/live")
async def liveness() -> HealthResponse:
    """Return success when the API process can serve requests."""

    return {"status": "ok"}


@router.get("/ready")
async def readiness() -> HealthResponse:
    """Return foundation readiness.

    Dependency-aware checks are introduced with local infrastructure in
    Sub-phase 0.4.
    """

    return {"status": "ok"}

