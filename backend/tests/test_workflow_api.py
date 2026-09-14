"""Workflow-run API and redaction tests."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.workflows import (
    WorkflowExecutionContext,
    create_configured_response_generator,
    workflow_execution_context,
    workflow_run_service,
)
from app.core.config import Settings
from app.domain.clinical import ClinicalRecordSummary, PatientSummary
from app.domain.generation import GroundedGenerationRequest, ResponseGenerationResult
from app.domain.safety import SafetyDecision, SafetyResult
from app.domain.workflow import WorkflowRunSnapshot, WorkflowStatus, WorkflowTransition
from app.main import app
from app.services.anthropic_response import AnthropicResponseGenerator
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.services.ollama_response import OllamaResponseGenerator
from app.services.openai_response import OpenAIResponseGenerator
from app.services.sqlite_workflow_runs import SqliteWorkflowRunStore
from app.services.workflow_runs import WorkflowRunService
from app.tools.response import ResponseGenerator
from app.tools.workflow_runs import WorkflowRunStore, WorkflowRunStoreError
from app.workflow.runtime import WorkflowExecutionPolicy, WorkflowRuntime
from tests.guideline_fixtures import SufficientGuidelineRetriever

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_configured_response_generator_defaults_to_deterministic() -> None:
    configured = create_configured_response_generator(Settings(_env_file=None))

    assert isinstance(configured, DeterministicResponseGenerator)


@pytest.mark.anyio
async def test_configured_response_generator_selects_openai() -> None:
    configured = create_configured_response_generator(
        Settings(
            _env_file=None,
            llm_provider="openai",
            llm_api_key="synthetic-test-secret",
        )
    )

    assert isinstance(configured, OpenAIResponseGenerator)
    await configured.close()


@pytest.mark.anyio
async def test_configured_response_generator_selects_anthropic() -> None:
    configured = create_configured_response_generator(
        Settings(
            _env_file=None,
            llm_provider="anthropic",
            llm_api_key="synthetic-test-secret",
        )
    )

    assert isinstance(configured, AnthropicResponseGenerator)
    await configured.close()


@pytest.mark.anyio
async def test_configured_response_generator_selects_ollama() -> None:
    configured = create_configured_response_generator(
        Settings(_env_file=None, llm_provider="ollama")
    )

    assert isinstance(configured, OllamaResponseGenerator)
    await configured.close()


def test_llm_timeout_setting_fits_response_execution_policy() -> None:
    settings = Settings(_env_file=None, llm_request_timeout_seconds=300)

    policy = WorkflowExecutionPolicy(
        timeout_seconds=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )

    assert policy.timeout_seconds == 300


@dataclass(frozen=True)
class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequentialIds:
    def __init__(self, start: int) -> None:
        self.value = start

    def new(self) -> UUID:
        result = UUID(int=self.value)
        self.value += 1
        return result


class StaticPatientReader:
    async def get(self, patient_id: str) -> PatientSummary:
        return PatientSummary(
            patient_id=patient_id,
            conditions=[
                ClinicalRecordSummary(
                    code="private-code",
                    display="Private synthetic condition",
                )
            ],
        )


class ReviewResponseGenerator:
    async def generate(
        self,
        *,
        request: GroundedGenerationRequest,
    ) -> ResponseGenerationResult:
        del request
        return ResponseGenerationResult.model_validate(
            {
                "draft": {
                    "answer": "Start this medication dose based on guideline evidence."
                },
                "metadata": {"generator": "deterministic"},
            }
        )


class FailingStore:
    async def initialize(self) -> None:
        return None

    async def save(self, snapshot: WorkflowRunSnapshot) -> None:
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def list_pending_review(self) -> list[WorkflowRunSnapshot]:
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def save_if_review_version(
        self,
        snapshot: WorkflowRunSnapshot,
        *,
        expected_review_version: int,
    ) -> bool:
        del snapshot, expected_review_version
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def list_incomplete(self) -> list[WorkflowRunSnapshot]:
        return []


def execution_context(
    store: WorkflowRunStore,
    *,
    response_generator: ResponseGenerator | None = None,
) -> WorkflowExecutionContext:
    clock = FixedClock()
    service = WorkflowRunService(
        store=store,
        clock=clock,
        workflow_ids=SequentialIds(100),
        correlation_ids=SequentialIds(200),
        trace_ids=SequentialIds(300),
        audit_event_ids=SequentialIds(400),
    )
    runtime = WorkflowRuntime(
        clock=clock,
        intent_classifier=DeterministicIntentClassifier(),
        patient_summary_reader=StaticPatientReader(),
        safety_policy=DeterministicSafetyPolicy(),
        post_generation_safety_policy=DeterministicSafetyPolicy(),
        response_generator=response_generator or DeterministicResponseGenerator(),
        audit_event_ids=SequentialIds(500),
        guideline_retriever=SufficientGuidelineRetriever(),
    )
    return WorkflowExecutionContext(service=service, runtime=runtime)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_create_and_inspect_redacted_workflow_run(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    context = execution_context(store)

    async def context_override() -> WorkflowExecutionContext:
        return context

    async def service_override() -> WorkflowRunService:
        return context.service

    app.dependency_overrides[workflow_execution_context] = context_override
    app.dependency_overrides[workflow_run_service] = service_override
    try:
        created = await client.post(
            "/api/v1/workflows",
            json={
                "patient_id": "synthetic-patient-1",
                "query": "private query marker about conditions",
            },
        )
        workflow_id = created.json()["data"]["workflow_id"]
        inspected = await client.get(f"/api/v1/workflows/{workflow_id}")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert inspected.status_code == 200
    payload = created.json()
    UUID(payload["request_id"])
    UUID(payload["data"]["correlation_id"])
    UUID(payload["data"]["trace_id"])
    assert payload["data"]["status"] == "completed"
    assert len(payload["data"]["final_response"]["citations"]) == 1
    assert payload["data"]["guideline_evidence"] == {
        "assessment": "sufficient",
        "policy_version": "retrieval-v1",
        "query_fingerprint": "0" * 64,
        "match_count": 1,
        "document_ids": ["who-synthetic-guideline"],
        "chunk_ids": ["who-synthetic-guideline.0"],
    }
    assert inspected.json()["data"] == payload["data"]
    for sensitive in (
        "private query marker",
        "synthetic-patient-1",
        "private-code",
        "Private synthetic condition",
        "patient_data",
        "user_query",
        "Reviewed bounded evidence chunk",
    ):
        assert sensitive not in created.text
        assert sensitive not in inspected.text


@pytest.mark.anyio
async def test_create_workflow_streams_redacted_langgraph_node_events(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    context = execution_context(store)

    async def context_override() -> WorkflowExecutionContext:
        return context

    app.dependency_overrides[workflow_execution_context] = context_override
    try:
        response = await client.post(
            "/api/v1/workflows",
            headers={"Accept": "text/event-stream"},
            json={
                "patient_id": "synthetic-patient-1",
                "query": "private streaming query about conditions",
            },
        )
    finally:
        app.dependency_overrides.clear()

    events: list[tuple[str, dict[str, object]]] = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert events[0][0] == "workflow"
    assert events[0][1]["phase"] == "queued"
    lifecycle = [
        (event[1]["node"], event[1]["phase"])
        for event in events
        if event[0] == "workflow" and event[1]["node"] is not None
    ]
    assert lifecycle == [
        ("begin_execution", "started"),
        ("begin_execution", "completed"),
        ("classify_intent", "started"),
        ("classify_intent", "completed"),
        ("retrieve_patient", "started"),
        ("retrieve_patient", "completed"),
        ("retrieve_guidelines", "started"),
        ("retrieve_guidelines", "completed"),
        ("safety_precheck", "started"),
        ("safety_precheck", "completed"),
        ("generate_response", "started"),
        ("generate_response", "completed"),
        ("post_generation_safety", "started"),
        ("post_generation_safety", "completed"),
        ("finalize_response", "started"),
        ("finalize_response", "completed"),
    ]
    final_payload = events[-1][1]
    final_data = final_payload["data"]
    assert isinstance(final_data, dict)
    assert final_data["status"] == "completed"
    assert await context.service.get(UUID(str(final_data["workflow_id"])))
    for sensitive in (
        "private streaming query",
        "synthetic-patient-1",
        "private-code",
        "Private synthetic condition",
        "patient_data",
        "user_query",
    ):
        assert sensitive not in response.text


@pytest.mark.anyio
async def test_review_queue_and_approval_api(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    context = execution_context(store, response_generator=ReviewResponseGenerator())

    async def context_override() -> WorkflowExecutionContext:
        return context

    async def service_override() -> WorkflowRunService:
        return context.service

    app.dependency_overrides[workflow_execution_context] = context_override
    app.dependency_overrides[workflow_run_service] = service_override
    try:
        created = await client.post(
            "/api/v1/workflows",
            json={
                "patient_id": "synthetic-patient-1",
                "query": "private query marker about medications",
            },
        )
        workflow_id = created.json()["data"]["workflow_id"]
        reviews = await client.get("/api/v1/workflows/reviews")
        detail = await client.get(f"/api/v1/workflows/{workflow_id}/review")
        approved = await client.post(
            f"/api/v1/workflows/{workflow_id}/review-actions",
            json={
                "action": "approve",
                "reviewer_id": "reviewer-1",
                "rationale": "Synthetic reviewer approval.",
                "review_version": 0,
            },
        )
        duplicate = await client.post(
            f"/api/v1/workflows/{workflow_id}/review-actions",
            json={
                "action": "approve",
                "reviewer_id": "reviewer-1",
                "rationale": "Duplicate synthetic approval.",
                "review_version": 0,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "pending_review"
    assert reviews.status_code == 200
    assert len(reviews.json()["data"]) == 1
    assert detail.status_code == 200
    assert detail.json()["data"]["review_version"] == 0
    assert approved.status_code == 200
    approved_data = approved.json()["data"]
    assert approved_data["status"] == "completed"
    assert approved_data["review_version"] == 1
    assert approved_data["final_response"]["answer"] == (
        "Start this medication dose based on guideline evidence."
    )
    assert approved_data["review_record"]["reviewer_id"] == "reviewer-1"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "stale_review_action"
    for sensitive in (
        "private query marker",
        "synthetic-patient-1",
        "private-code",
        "Private synthetic condition",
        "patient_data",
        "user_query",
        "Reviewed bounded evidence chunk",
    ):
        assert sensitive not in reviews.text
        assert sensitive not in detail.text
        assert sensitive not in approved.text


@pytest.mark.anyio
async def test_pre_generation_review_approval_returns_conflict(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    context = execution_context(store)
    snapshot = WorkflowRunSnapshot(
        workflow_id=UUID(int=901),
        correlation_id=UUID(int=902),
        trace_id=UUID(int=903),
        status=WorkflowStatus.PENDING_REVIEW,
        created_at=NOW,
        updated_at=NOW,
        requires_human_review=True,
        safety_result=SafetyResult(
            decision=SafetyDecision.REVIEW,
            requires_human_review=True,
            policy_version="safety-precheck-v1",
        ),
        transitions=[
            WorkflowTransition(
                from_status=WorkflowStatus.QUEUED,
                to_status=WorkflowStatus.RUNNING,
                occurred_at=NOW,
                step="begin_execution",
            ),
            WorkflowTransition(
                from_status=WorkflowStatus.RUNNING,
                to_status=WorkflowStatus.PENDING_REVIEW,
                occurred_at=NOW,
                step="safety_precheck",
            ),
        ],
    )
    await store.save(snapshot)

    async def service_override() -> WorkflowRunService:
        return context.service

    app.dependency_overrides[workflow_run_service] = service_override
    try:
        approved = await client.post(
            f"/api/v1/workflows/{snapshot.workflow_id}/review-actions",
            json={
                "action": "approve",
                "reviewer_id": "reviewer-1",
                "rationale": "Synthetic reviewer approval.",
                "review_version": 0,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert approved.status_code == 409
    assert approved.json()["error"]["code"] == "review_checkpoint_not_resumable"
    assert "reviewer-1" not in approved.text


@pytest.mark.anyio
async def test_invalid_request_returns_safe_error_without_echo(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    context = execution_context(
        SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    )

    async def context_override() -> WorkflowExecutionContext:
        return context

    app.dependency_overrides[workflow_execution_context] = context_override
    try:
        response = await client.post(
            "/api/v1/workflows",
            json={
                "patient_id": "invalid/patient",
                "query": "private invalid query marker",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_workflow_request"
    assert "private invalid query marker" not in response.text
    assert "invalid/patient" not in response.text


@pytest.mark.anyio
async def test_malformed_json_uses_redacted_validation_envelope(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/workflows",
        content='{"query":"private malformed marker"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "private malformed marker" not in response.text


@pytest.mark.anyio
async def test_missing_and_invalid_workflow_ids_return_safe_errors(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    context = execution_context(
        SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    )
    await context.service.store.initialize()

    async def service_override() -> WorkflowRunService:
        return context.service

    app.dependency_overrides[workflow_run_service] = service_override
    try:
        invalid = await client.get("/api/v1/workflows/not-a-uuid")
        missing = await client.get(f"/api/v1/workflows/{UUID(int=999)}")
    finally:
        app.dependency_overrides.clear()

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_workflow_id"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "workflow_not_found"


@pytest.mark.anyio
async def test_storage_failure_is_redacted(
    client: AsyncClient,
) -> None:
    context = execution_context(FailingStore())

    async def context_override() -> WorkflowExecutionContext:
        return context

    app.dependency_overrides[workflow_execution_context] = context_override
    try:
        response = await client.post(
            "/api/v1/workflows",
            json={
                "patient_id": "synthetic-patient-1",
                "query": "What precautions relate to these conditions?",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "workflow_storage_unavailable"
    assert "sensitive sqlite failure" not in response.text
