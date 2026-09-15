"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.evidence import router as evidence_router
from app.api.health import router as health_router
from app.api.patients import router as patient_router
from app.api.workflows import initialize_workflow_runs
from app.api.workflows import router as workflow_router
from app.core.config import get_settings
from app.core.observability import (
    RequestBodyLimitMiddleware,
    RequestObservabilityMiddleware,
    SecurityHeadersMiddleware,
    WorkflowRateLimitMiddleware,
)
from app.domain.api import ApiError, ErrorDetail


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize application storage and recover interrupted workflow runs."""

    del application
    await initialize_workflow_runs()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    description=(
        "Educational workflow orchestration over synthetic healthcare data. "
        "Not a medical device."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    """Return a stable validation error without echoing untrusted input."""

    del request, error
    payload = ApiError(
        request_id=uuid4(),
        error=ErrorDetail(
            code="invalid_request",
            message="The request could not be validated.",
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=payload.model_dump(mode="json"),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestObservabilityMiddleware)
app.add_middleware(
    WorkflowRateLimitMiddleware,
    requests_per_minute=settings.workflow_rate_limit_per_minute,
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.include_router(health_router)
app.include_router(evidence_router)
app.include_router(patient_router)
app.include_router(workflow_router)
