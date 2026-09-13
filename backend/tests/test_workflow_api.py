"""Workflow-run API and redaction tests."""

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
from app.domain.workflow import WorkflowRunSnapshot
from app.main import app
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.services.openai_response import OpenAIResponseGenerator
from app.services.sqlite_workflow_runs import SqliteWorkflowRunStore
from app.services.workflow_runs import WorkflowRunService
from app.tools.workflow_runs import WorkflowRunStore, WorkflowRunStoreError
from app.workflow.runtime import WorkflowRuntime
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


class FailingStore:
    async def initialize(self) -> None:
        return None

    async def save(self, snapshot: WorkflowRunSnapshot) -> None:
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        raise WorkflowRunStoreError("sensitive sqlite failure")

    async def list_incomplete(self) -> list[WorkflowRunSnapshot]:
        return []


def execution_context(store: WorkflowRunStore) -> WorkflowExecutionContext:
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
        response_generator=DeterministicResponseGenerator(),
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
