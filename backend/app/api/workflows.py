"""Workflow-run creation and redacted status inspection endpoints."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.config import get_settings
from app.domain.api import ApiError, ApiSuccess, ErrorDetail
from app.domain.workflow import WorkflowRunRequest, WorkflowRunSnapshot
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.services.hapi_fhir import create_hapi_fhir_client
from app.services.patient_summary import create_patient_summary_service
from app.services.sqlite_workflow_runs import SqliteWorkflowRunStore
from app.services.workflow_runs import (
    RandomWorkflowIdentityFactory,
    WorkflowRunService,
)
from app.tools.workflow_runs import WorkflowRunStore, WorkflowRunStoreError
from app.workflow.runtime import (
    RandomAuditEventIdFactory,
    SystemWorkflowClock,
    WorkflowExecutionPolicy,
    WorkflowRuntime,
)

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": ApiError},
    status.HTTP_404_NOT_FOUND: {"model": ApiError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiError},
}


def _error_response(
    *,
    request_id: UUID,
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
) -> JSONResponse:
    payload = ApiError(
        request_id=request_id,
        error=ErrorDetail(code=code, message=message, field=field),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


@lru_cache
def workflow_run_store() -> SqliteWorkflowRunStore:
    """Return the process-owned workflow checkpoint store."""

    return SqliteWorkflowRunStore(get_settings().database_url)


def create_workflow_run_service(store: WorkflowRunStore) -> WorkflowRunService:
    """Build workflow lifecycle services from application-owned dependencies."""

    identity_factory = RandomWorkflowIdentityFactory()
    return WorkflowRunService(
        store=store,
        clock=SystemWorkflowClock(),
        workflow_ids=identity_factory,
        correlation_ids=identity_factory,
        trace_ids=identity_factory,
        audit_event_ids=RandomAuditEventIdFactory(),
    )


async def workflow_run_service(
    store: Annotated[WorkflowRunStore, Depends(workflow_run_store)],
) -> WorkflowRunService:
    """Initialize and provide the workflow lifecycle service."""

    await store.initialize()
    return create_workflow_run_service(store)


@dataclass(frozen=True)
class WorkflowExecutionContext:
    """Request-scoped lifecycle service and graph runtime."""

    service: WorkflowRunService
    runtime: WorkflowRuntime


async def workflow_execution_context(
    service: Annotated[WorkflowRunService, Depends(workflow_run_service)],
) -> AsyncIterator[WorkflowExecutionContext]:
    """Provide a workflow runtime and close its HAPI transport."""

    settings = get_settings()
    async with create_hapi_fhir_client(settings) as client:
        audit_event_ids = RandomAuditEventIdFactory()
        yield WorkflowExecutionContext(
            service=service,
            runtime=WorkflowRuntime(
                clock=service.clock,
                intent_classifier=DeterministicIntentClassifier(),
                patient_summary_reader=create_patient_summary_service(
                    settings,
                    client,
                ),
                safety_policy=DeterministicSafetyPolicy(),
                response_generator=DeterministicResponseGenerator(),
                audit_event_ids=audit_event_ids,
                execution_policy=WorkflowExecutionPolicy(
                    timeout_seconds=settings.workflow_node_timeout_seconds,
                    max_retries=settings.workflow_node_max_retries,
                ),
            ),
        )


async def initialize_workflow_runs() -> int:
    """Initialize storage and safely fail checkpoints interrupted by restart."""

    store = workflow_run_store()
    await store.initialize()
    return await create_workflow_run_service(store).recover_interrupted()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiSuccess[WorkflowRunSnapshot],
    responses=ERROR_RESPONSES,
)
async def create_workflow_run(
    raw_request: Annotated[object, Body()],
    context: Annotated[WorkflowExecutionContext, Depends(workflow_execution_context)],
) -> ApiSuccess[WorkflowRunSnapshot] | JSONResponse:
    """Execute one validated synthetic clinical-QA workflow synchronously."""

    request_id = uuid4()
    try:
        request = WorkflowRunRequest.model_validate(raw_request)
    except ValidationError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_workflow_request",
            message="The workflow request is invalid.",
        )
    try:
        snapshot = await context.service.create(request, runtime=context.runtime)
    except WorkflowRunStoreError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="workflow_storage_unavailable",
            message="Workflow storage is unavailable.",
        )
    return ApiSuccess(request_id=request_id, data=snapshot)


@router.get(
    "/{workflow_id}",
    response_model=ApiSuccess[WorkflowRunSnapshot],
    responses=ERROR_RESPONSES,
)
async def get_workflow_run(
    workflow_id: str,
    service: Annotated[WorkflowRunService, Depends(workflow_run_service)],
) -> ApiSuccess[WorkflowRunSnapshot] | JSONResponse:
    """Return one redacted workflow checkpoint."""

    request_id = uuid4()
    try:
        parsed_id = UUID(workflow_id)
    except ValueError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_workflow_id",
            message="The workflow run ID is invalid.",
            field="workflow_id",
        )
    try:
        snapshot = await service.get(parsed_id)
    except WorkflowRunStoreError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="workflow_storage_unavailable",
            message="Workflow storage is unavailable.",
        )
    if snapshot is None:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message="The workflow run was not found.",
            field="workflow_id",
        )
    return ApiSuccess(request_id=request_id, data=snapshot)
