"""Process liveness and dependency readiness endpoints."""

from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Depends, Response, status

from app.core.config import get_settings
from app.core.observability import metrics_registry
from app.services.readiness import ReadinessReport, check_dependencies

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(TypedDict):
    """Response returned by foundation health checks."""

    status: Literal["ok"]


@router.get("/live")
async def liveness() -> HealthResponse:
    """Return success when the API process can serve requests."""

    return {"status": "ok"}


async def readiness_report() -> ReadinessReport:
    """Resolve dependency readiness for injection and test replacement."""

    return await check_dependencies(get_settings())


@router.get(
    "/ready",
    response_model=ReadinessReport,
    responses={503: {"model": ReadinessReport}},
)
async def readiness(
    response: Response,
    report: Annotated[ReadinessReport, Depends(readiness_report)],
) -> ReadinessReport:
    """Return 200 only when configured local dependencies are available."""

    if report.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@router.get("/metrics")
async def metrics() -> dict[str, object]:
    """Return process-local operational metrics without payload content."""

    return metrics_registry.snapshot()
