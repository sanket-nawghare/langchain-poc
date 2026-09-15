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
from app.domain.guidelines import GuidelineEvidenceSummary
from app.domain.safety import SafetyDecision, SafetyResult
from app.domain.workflow import (
    ResponseDraft,
    ReviewActionRequest,
    ReviewActionType,
    WorkflowRunRequest,
    WorkflowRunSnapshot,
    WorkflowStatus,
    WorkflowTransition,
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
    WorkflowReviewError,
    WorkflowRunService,
)
from app.tools.workflow_runs import WorkflowRunStoreError
from app.workflow.runtime import WorkflowRuntime
from tests.guideline_fixtures import (
    SufficientGuidelineRetriever,
    sufficient_guideline_result,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
PENDING_REVIEW_WORKFLOW_ID = UUID(int=900)


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


def pending_review_snapshot(
    *, workflow_id: UUID = PENDING_REVIEW_WORKFLOW_ID
) -> WorkflowRunSnapshot:
    result = sufficient_guideline_result()
    return WorkflowRunSnapshot(
        workflow_id=workflow_id,
        correlation_id=UUID(int=901),
        trace_id=UUID(int=902),
        status=WorkflowStatus.PENDING_REVIEW,
        created_at=NOW,
        updated_at=NOW,
        requires_human_review=True,
        guideline_evidence=GuidelineEvidenceSummary.from_retrieval_result(result),
        response_draft=ResponseDraft(
            answer="Start this medication dose based on guideline evidence."
        ),
        review_citations=[match.citation for match in result.matches],
        safety_result=SafetyResult(
            decision=SafetyDecision.PASS,
            requires_human_review=False,
            policy_version="safety-precheck-v1",
        ),
        post_generation_safety_result=SafetyResult(
            decision=SafetyDecision.REVIEW,
            requires_human_review=True,
            policy_version="safety-post-generation-v1",
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
                step="post_generation_safety",
            ),
        ],
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
async def test_service_streams_started_and_persisted_completed_node_updates(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    run_service = service(store)

    updates = [
        update
        async for update in run_service.stream(
            WorkflowRunRequest(
                patient_id="synthetic-patient-1",
                query="What precautions relate to these conditions?",
            ),
            runtime=runtime(FixedClock(), SequentialIds(500)),
        )
    ]

    assert updates[0][0:2] == (None, "queued")
    assert ("generate_response", "started") in [
        (node, phase) for node, phase, _ in updates
    ]
    assert updates[-1][0:2] == ("finalize_response", "completed")
    final_snapshot = updates[-1][2]
    assert final_snapshot.status is WorkflowStatus.COMPLETED
    assert await store.get(final_snapshot.workflow_id) == final_snapshot


@pytest.mark.anyio
async def test_review_queue_lists_pending_redacted_projection(tmp_path: Path) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)

    reviews = await service(store).list_reviews()

    assert len(reviews) == 1
    assert reviews[0].workflow_id == snapshot.workflow_id
    assert reviews[0].review_version == 0
    assert reviews[0].response_draft == snapshot.response_draft
    assert reviews[0].citations == snapshot.review_citations
    serialized = reviews[0].model_dump_json()
    assert "synthetic-patient-1" not in serialized
    assert "patient_data" not in serialized


@pytest.mark.anyio
async def test_review_approval_finalizes_exact_persisted_draft_once(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)

    approved = await service(store).record_review_action(
        snapshot.workflow_id,
        ReviewActionRequest(
            action=ReviewActionType.APPROVE,
            reviewer_id="reviewer-1",
            rationale="Synthetic reviewer approval.",
            review_version=0,
        ),
    )
    duplicate_saved = await store.save_if_review_version(
        pending_review_snapshot(workflow_id=snapshot.workflow_id),
        expected_review_version=0,
    )

    assert approved.status == WorkflowStatus.COMPLETED
    assert approved.review_version == 1
    assert approved.final_response is not None
    assert snapshot.response_draft is not None
    assert approved.final_response.answer == snapshot.response_draft.answer
    assert approved.final_response.citations == snapshot.review_citations
    assert [transition.step for transition in approved.transitions[-2:]] == [
        "review_approved",
        "finalize_reviewed_response",
    ]
    assert approved.audit_log[-1].actor_id == "reviewer-1"
    assert approved.audit_log[-1].details["action"] == "approve"
    assert duplicate_saved is False
    assert await store.get(snapshot.workflow_id) == approved


@pytest.mark.anyio
async def test_review_reject_or_request_changes_terminates_without_response(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)

    rejected = await service(store).record_review_action(
        snapshot.workflow_id,
        ReviewActionRequest(
            action=ReviewActionType.REQUEST_CHANGES,
            reviewer_id="reviewer-1",
            rationale="Needs bounded changes.",
            review_version=0,
        ),
    )

    assert rejected.status == WorkflowStatus.REJECTED
    assert rejected.final_response is None
    assert rejected.review_version == 1
    assert rejected.transitions[-1].step == "review_changes_requested"
    assert rejected.audit_log[-1].details["action"] == "request_changes"


@pytest.mark.anyio
async def test_stale_review_action_is_rejected(tmp_path: Path) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)

    with pytest.raises(RuntimeError, match="stale_review_action"):
        await service(store).record_review_action(
            snapshot.workflow_id,
            ReviewActionRequest(
                action=ReviewActionType.APPROVE,
                reviewer_id="reviewer-1",
                rationale="Synthetic reviewer approval.",
                review_version=1,
            ),
        )


@pytest.mark.anyio
async def test_pending_review_survives_restart_without_auto_execution(
    tmp_path: Path,
) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)

    recovered_count = await service(store).recover_interrupted()
    recovered = await store.get(snapshot.workflow_id)

    assert recovered_count == 0
    assert recovered == snapshot
    assert await service(store).get_review(snapshot.workflow_id) is not None


@pytest.mark.anyio
async def test_concurrent_review_approval_resumes_only_once(tmp_path: Path) -> None:
    store = SqliteWorkflowRunStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    await store.initialize()
    snapshot = pending_review_snapshot()
    await store.save(snapshot)
    run_service = service(store)

    async def approve() -> WorkflowRunSnapshot | WorkflowReviewError:
        try:
            return await run_service.record_review_action(
                snapshot.workflow_id,
                ReviewActionRequest(
                    action=ReviewActionType.APPROVE,
                    reviewer_id="reviewer-1",
                    rationale="Synthetic reviewer approval.",
                    review_version=0,
                ),
            )
        except WorkflowReviewError as error:
            return error

    results = await asyncio.gather(approve(), approve())
    approvals = [item for item in results if isinstance(item, WorkflowRunSnapshot)]
    errors = [item for item in results if isinstance(item, WorkflowReviewError)]
    persisted = await store.get(snapshot.workflow_id)

    assert len(approvals) == 1
    assert len(errors) == 1
    assert errors[0].code == "stale_review_action"
    assert persisted == approvals[0]
    assert persisted is not None
    assert persisted.status == WorkflowStatus.COMPLETED
    assert [transition.step for transition in persisted.transitions].count(
        "finalize_reviewed_response"
    ) == 1
    assert persisted.review_version == 1


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
