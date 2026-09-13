"""Workflow-run creation and redacted status inspection endpoints."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.domain.api import ApiError, ApiSuccess, ErrorDetail
from app.domain.workflow import (
    ReviewActionRequest,
    ReviewQueueItem,
    WorkflowRunRequest,
    WorkflowRunSnapshot,
)
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.services.hapi_fhir import create_hapi_fhir_client
from app.services.local_guideline_retrieval import LocalGuidelineRetriever
from app.services.openai_response import (
    OpenAIResponseGenerator,
    create_openai_response_generator,
)
from app.services.patient_summary import create_patient_summary_service
from app.services.sqlite_workflow_runs import SqliteWorkflowRunStore
from app.services.workflow_runs import (
    RandomWorkflowIdentityFactory,
    WorkflowReviewError,
    WorkflowRunService,
)
from app.tools.response import ResponseGenerator
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
    status.HTTP_409_CONFLICT: {"model": ApiError},
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


def create_configured_response_generator(settings: Settings) -> ResponseGenerator:
    """Select the configured generation implementation at runtime."""

    if settings.llm_provider == "openai":
        return create_openai_response_generator(settings)
    return DeterministicResponseGenerator()


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
    """Provide a workflow runtime and close request-scoped dependency clients."""

    settings = get_settings()
    guideline_retriever = LocalGuidelineRetriever(settings)
    response_generator = create_configured_response_generator(settings)
    try:
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
                    post_generation_safety_policy=DeterministicSafetyPolicy(),
                    response_generator=response_generator,
                    audit_event_ids=audit_event_ids,
                    guideline_retriever=guideline_retriever,
                    execution_policy=WorkflowExecutionPolicy(
                        timeout_seconds=settings.workflow_node_timeout_seconds,
                        max_retries=settings.workflow_node_max_retries,
                    ),
                    response_execution_policy=WorkflowExecutionPolicy(
                        timeout_seconds=settings.llm_request_timeout_seconds,
                        max_retries=settings.llm_max_retries,
                    ),
                ),
            )
    finally:
        if isinstance(response_generator, OpenAIResponseGenerator):
            await response_generator.close()
        await guideline_retriever.close()


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
    "/reviews",
    response_model=ApiSuccess[list[ReviewQueueItem]],
    responses=ERROR_RESPONSES,
)
async def list_pending_reviews(
    service: Annotated[WorkflowRunService, Depends(workflow_run_service)],
) -> ApiSuccess[list[ReviewQueueItem]] | JSONResponse:
    """Return pending workflow reviews as redacted reviewer projections."""

    request_id = uuid4()
    try:
        reviews = await service.list_reviews()
    except WorkflowRunStoreError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="workflow_storage_unavailable",
            message="Workflow storage is unavailable.",
        )
    return ApiSuccess(request_id=request_id, data=reviews)


@router.get(
    "/{workflow_id}/review",
    response_model=ApiSuccess[ReviewQueueItem],
    responses=ERROR_RESPONSES,
)
async def get_pending_review(
    workflow_id: str,
    service: Annotated[WorkflowRunService, Depends(workflow_run_service)],
) -> ApiSuccess[ReviewQueueItem] | JSONResponse:
    """Return one pending workflow review projection."""

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
        review = await service.get_review(parsed_id)
    except WorkflowRunStoreError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="workflow_storage_unavailable",
            message="Workflow storage is unavailable.",
        )
    if review is None:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_404_NOT_FOUND,
            code="review_not_found",
            message="The pending review was not found.",
            field="workflow_id",
        )
    return ApiSuccess(request_id=request_id, data=review)


@router.post(
    "/{workflow_id}/review-actions",
    response_model=ApiSuccess[WorkflowRunSnapshot],
    responses=ERROR_RESPONSES,
)
async def record_review_action(
    workflow_id: str,
    raw_request: Annotated[object, Body()],
    service: Annotated[WorkflowRunService, Depends(workflow_run_service)],
) -> ApiSuccess[WorkflowRunSnapshot] | JSONResponse:
    """Record one attributable review action with optimistic concurrency."""

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
        request = ReviewActionRequest.model_validate(raw_request)
    except ValidationError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_review_action",
            message="The review action is invalid.",
        )
    try:
        snapshot = await service.record_review_action(parsed_id, request)
    except WorkflowReviewError as error:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code in {"workflow_not_found", "review_not_found"}
            else status.HTTP_409_CONFLICT
            if error.code in {"stale_review_action", "workflow_not_pending_review"}
            else status.HTTP_400_BAD_REQUEST
        )
        return _error_response(
            request_id=request_id,
            status_code=status_code,
            code=error.code,
            message="The review action could not be applied.",
        )
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
