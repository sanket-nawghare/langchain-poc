"""Workflow-run persistence, lifecycle, and recovery tests."""

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.clinical import ClinicalRecordSummary, PatientSummary
from app.domain.workflow import (
    WorkflowRunRequest,
    WorkflowRunSnapshot,
    WorkflowStatus,
)
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.services.deterministic_response import DeterministicResponseGenerator
from app.services.deterministic_safety import DeterministicSafetyPolicy
from app.services.sqlite_workflow_runs import (
    SqliteWorkflowRunStore,
    sqlite_path,
)
from app.services.workflow_runs import (
    INTERRUPTED_FAILURE_CODE,
    RECOVERY_STEP,
    WorkflowRunService,
)
from app.tools.workflow_runs import WorkflowRunStoreError
from app.workflow.runtime import WorkflowRuntime
from tests.guideline_fixtures import SufficientGuidelineRetriever

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequentialIds:
    def __init__(self, start: int = 1) -> None:
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
                    code="synthetic",
                    display="Synthetic condition",
                )
            ],
        )


def runtime(clock: FixedClock, audit_ids: SequentialIds) -> WorkflowRuntime:
    return WorkflowRuntime(
        clock=clock,
        intent_classifier=DeterministicIntentClassifier(),
        patient_summary_reader=StaticPatientReader(),
        safety_policy=DeterministicSafetyPolicy(),
        post_generation_safety_policy=DeterministicSafetyPolicy(),
        response_generator=DeterministicResponseGenerator(),
        audit_event_ids=audit_ids,
        guideline_retriever=SufficientGuidelineRetriever(),
    )


def service(store: SqliteWorkflowRunStore) -> WorkflowRunService:
    clock = FixedClock()
    return WorkflowRunService(
        store=store,
        clock=clock,
        workflow_ids=SequentialIds(100),
        correlation_ids=SequentialIds(200),
        trace_ids=SequentialIds(300),
        audit_event_ids=SequentialIds(400),
    )


@pytest.mark.anyio
async def test_sqlite_store_round_trips_redacted_checkpoint(tmp_path: Path) -> None:
    database_path = tmp_path / "workflow.db"
    store = SqliteWorkflowRunStore(f"sqlite:///{database_path}")
    snapshot = WorkflowRunSnapshot.queued(
        workflow_id=UUID(int=1),
        correlation_id=UUID(int=2),
        trace_id=UUID(int=3),
        created_at=NOW,
    )

    await store.initialize()
    await store.save(snapshot)

    assert await store.get(snapshot.workflow_id) == snapshot
    assert await store.list_incomplete() == [snapshot]
    with sqlite3.connect(database_path) as connection:
        stored_json = connection.execute(
            "SELECT snapshot_json FROM workflow_runs"
        ).fetchone()[0]
    assert "user_query" not in stored_json
    assert "patient_data" not in stored_json
    assert "Synthetic condition" not in stored_json


def test_sqlite_store_rejects_unsupported_database_url() -> None:
    with pytest.raises(WorkflowRunStoreError, match="unsupported"):
        sqlite_path("postgresql://localhost/application")


def test_snapshot_rejects_nonqueued_status_without_transition_history() -> None:
    with pytest.raises(ValidationError, match="transitions"):
        WorkflowRunSnapshot(
            workflow_id=UUID(int=1),
            correlation_id=UUID(int=2),
            trace_id=UUID(int=3),
            status=WorkflowStatus.RUNNING,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.anyio
async def test_service_persists_queued_then_completed_checkpoint(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    run_service = service(store)

    snapshot = await run_service.create(
        WorkflowRunRequest(
            patient_id="synthetic-patient-1",
            query="What precautions relate to these conditions?",
        ),
        runtime=runtime(FixedClock(), SequentialIds(500)),
    )

    assert snapshot.status == WorkflowStatus.COMPLETED
    assert snapshot.final_response is not None
    assert len(snapshot.final_response.citations) == 1
    assert snapshot.guideline_evidence is not None
    assert snapshot.guideline_evidence.match_count == 1
    assert snapshot.trace_id == UUID(int=300)
    assert await run_service.get(snapshot.workflow_id) == snapshot
    assert await store.list_incomplete() == []
    serialized = snapshot.model_dump_json()
    assert "What precautions" not in serialized
    assert "Synthetic condition" not in serialized
    assert "Reviewed bounded evidence chunk" not in serialized
    values = snapshot.model_dump()
    evidence = dict(values["guideline_evidence"])
    evidence["chunk_ids"] = ["mismatched-chunk"]
    with pytest.raises(ValidationError, match="chunk IDs"):
        WorkflowRunSnapshot.model_validate({**values, "guideline_evidence": evidence})


@pytest.mark.anyio
async def test_concurrent_runs_receive_unique_identifiers(tmp_path: Path) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    run_service = service(store)
    request = WorkflowRunRequest(
        patient_id="synthetic-patient-1",
        query="What precautions relate to these conditions?",
    )

    snapshots = await asyncio.gather(
        *(
            run_service.create(
                request,
                runtime=runtime(FixedClock(), SequentialIds(500 + index * 20)),
            )
            for index in range(4)
        )
    )

    assert len({snapshot.workflow_id for snapshot in snapshots}) == 4
    assert len({snapshot.correlation_id for snapshot in snapshots}) == 4
    assert len({snapshot.trace_id for snapshot in snapshots}) == 4


@pytest.mark.anyio
async def test_restart_recovery_fails_incomplete_run_without_reexecution(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    queued = WorkflowRunSnapshot.queued(
        workflow_id=UUID(int=10),
        correlation_id=UUID(int=11),
        trace_id=UUID(int=12),
        created_at=NOW,
    )
    await store.save(queued)

    recovered_count = await service(store).recover_interrupted()
    recovered = await store.get(queued.workflow_id)

    assert recovered_count == 1
    assert recovered is not None
    assert recovered.status == WorkflowStatus.FAILED
    assert recovered.failure_code == INTERRUPTED_FAILURE_CODE
    assert recovered.transitions[-1].step == RECOVERY_STEP
    assert recovered.audit_log[-1].details["failure_code"] == (INTERRUPTED_FAILURE_CODE)
    assert await store.list_incomplete() == []
