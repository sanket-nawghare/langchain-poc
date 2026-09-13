"""Workflow-run creation, redacted checkpointing, and safe recovery."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.audit import ActorType, AuditEvent, AuditEventType
from app.domain.workflow import (
    GeneratedResponse,
    ReviewActionRequest,
    ReviewActionType,
    ReviewQueueItem,
    ReviewRecord,
    WorkflowRunRequest,
    WorkflowRunSnapshot,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from app.tools.workflow_runs import WorkflowRunStore
from app.workflow.graph import EDUCATIONAL_DISCLAIMER, execute_workflow
from app.workflow.runtime import AuditEventIdFactory, WorkflowClock, WorkflowRuntime

INTERRUPTED_FAILURE_CODE = "workflow_interrupted"
RECOVERY_STEP = "recover_interrupted"
REVIEW_ACTION_POLICY_VERSION = "review-action-v1"
REVIEW_APPROVED_STEP = "review_approved"
REVIEW_REJECTED_STEP = "review_rejected"
REVIEW_CHANGES_REQUESTED_STEP = "review_changes_requested"
REVIEW_FINALIZE_STEP = "finalize_reviewed_response"


class WorkflowReviewError(RuntimeError):
    """A review action could not be accepted safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkflowIdentityFactory(Protocol):
    """Application-owned UUID source for workflow identity."""

    def new(self) -> UUID:
        """Return a new opaque identifier."""


class RandomWorkflowIdentityFactory:
    """UUID4 workflow identity source."""

    def new(self) -> UUID:
        """Return a random UUID4."""

        return uuid4()


@dataclass(frozen=True)
class WorkflowRunService:
    """Execute workflows and persist redacted lifecycle checkpoints."""

    store: WorkflowRunStore
    clock: WorkflowClock
    workflow_ids: WorkflowIdentityFactory
    correlation_ids: WorkflowIdentityFactory
    trace_ids: WorkflowIdentityFactory
    audit_event_ids: AuditEventIdFactory

    async def create(
        self,
        request: WorkflowRunRequest,
        *,
        runtime: WorkflowRuntime,
    ) -> WorkflowRunSnapshot:
        """Persist queued state, execute once, and persist the final checkpoint."""

        created_at = self.clock.now()
        workflow_id = self.workflow_ids.new()
        correlation_id = self.correlation_ids.new()
        trace_id = self.trace_ids.new()
        queued = WorkflowRunSnapshot.queued(
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            created_at=created_at,
        )
        await self.store.save(queued)

        execution = await execute_workflow(
            WorkflowState(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                created_at=created_at,
                updated_at=created_at,
                user_query=request.query,
                patient_id=request.patient_id,
            ),
            runtime=runtime,
        )
        completed = WorkflowRunSnapshot.from_execution(
            execution,
            trace_id=trace_id,
        )
        await self.store.save(completed)
        return completed

    async def get(self, workflow_id: UUID) -> WorkflowRunSnapshot | None:
        """Return one safely redacted workflow checkpoint."""

        return await self.store.get(workflow_id)

    async def list_reviews(self) -> list[ReviewQueueItem]:
        """Return pending review items as safe reviewer projections."""

        snapshots = await self.store.list_pending_review()
        return [ReviewQueueItem.from_snapshot(snapshot) for snapshot in snapshots]

    async def get_review(self, workflow_id: UUID) -> ReviewQueueItem | None:
        """Return one pending review projection when it exists."""

        snapshot = await self.store.get(workflow_id)
        if snapshot is None or snapshot.status is not WorkflowStatus.PENDING_REVIEW:
            return None
        return ReviewQueueItem.from_snapshot(snapshot)

    async def record_review_action(
        self,
        workflow_id: UUID,
        request: ReviewActionRequest,
    ) -> WorkflowRunSnapshot:
        """Persist one attributable review action with optimistic concurrency."""

        snapshot = await self.store.get(workflow_id)
        if snapshot is None:
            raise WorkflowReviewError("workflow_not_found")
        if snapshot.status is not WorkflowStatus.PENDING_REVIEW:
            raise WorkflowReviewError("workflow_not_pending_review")
        if request.review_version != snapshot.review_version:
            raise WorkflowReviewError("stale_review_action")

        occurred_at = self.clock.now()
        next_version = snapshot.review_version + 1
        review_record = ReviewRecord(
            action=request.action,
            reviewer_id=request.reviewer_id,
            rationale=request.rationale,
            policy_version=REVIEW_ACTION_POLICY_VERSION,
            reviewed_at=occurred_at,
            review_version=next_version,
        )
        audit_event = AuditEvent(
            event_id=self.audit_event_ids.new(),
            workflow_id=snapshot.workflow_id,
            correlation_id=snapshot.correlation_id,
            event_type=AuditEventType.REVIEW_RECORDED,
            occurred_at=occurred_at,
            actor_type=ActorType.REVIEWER,
            actor_id=request.reviewer_id,
            details={
                "action": request.action.value,
                "policy_version": REVIEW_ACTION_POLICY_VERSION,
                "review_version": next_version,
            },
        )

        if request.action is ReviewActionType.APPROVE:
            if snapshot.response_draft is None or not snapshot.review_citations:
                raise WorkflowReviewError("review_checkpoint_not_resumable")
            running_transition = WorkflowTransition(
                from_status=WorkflowStatus.PENDING_REVIEW,
                to_status=WorkflowStatus.RUNNING,
                occurred_at=occurred_at,
                step=REVIEW_APPROVED_STEP,
            )
            completed_transition = WorkflowTransition(
                from_status=WorkflowStatus.RUNNING,
                to_status=WorkflowStatus.COMPLETED,
                occurred_at=occurred_at,
                step=REVIEW_FINALIZE_STEP,
            )
            updated = WorkflowRunSnapshot(
                workflow_id=snapshot.workflow_id,
                correlation_id=snapshot.correlation_id,
                trace_id=snapshot.trace_id,
                status=WorkflowStatus.COMPLETED,
                created_at=snapshot.created_at,
                updated_at=occurred_at,
                requires_human_review=False,
                guideline_evidence=snapshot.guideline_evidence,
                response_draft=snapshot.response_draft,
                review_citations=snapshot.review_citations,
                safety_result=snapshot.safety_result,
                post_generation_safety_result=snapshot.post_generation_safety_result,
                final_response=GeneratedResponse(
                    answer=snapshot.response_draft.answer,
                    citations=snapshot.review_citations,
                    disclaimer=EDUCATIONAL_DISCLAIMER,
                ),
                review_version=next_version,
                review_record=review_record,
                transitions=[
                    *snapshot.transitions,
                    running_transition,
                    completed_transition,
                ],
                audit_log=[*snapshot.audit_log, audit_event],
            )
        else:
            step = (
                REVIEW_REJECTED_STEP
                if request.action is ReviewActionType.REJECT
                else REVIEW_CHANGES_REQUESTED_STEP
            )
            transition = WorkflowTransition(
                from_status=WorkflowStatus.PENDING_REVIEW,
                to_status=WorkflowStatus.REJECTED,
                occurred_at=occurred_at,
                step=step,
            )
            updated = WorkflowRunSnapshot(
                workflow_id=snapshot.workflow_id,
                correlation_id=snapshot.correlation_id,
                trace_id=snapshot.trace_id,
                status=WorkflowStatus.REJECTED,
                created_at=snapshot.created_at,
                updated_at=occurred_at,
                requires_human_review=False,
                guideline_evidence=snapshot.guideline_evidence,
                response_draft=snapshot.response_draft,
                review_citations=snapshot.review_citations,
                safety_result=snapshot.safety_result,
                post_generation_safety_result=snapshot.post_generation_safety_result,
                review_version=next_version,
                review_record=review_record,
                transitions=[*snapshot.transitions, transition],
                audit_log=[*snapshot.audit_log, audit_event],
            )

        saved = await self.store.save_if_review_version(
            updated,
            expected_review_version=request.review_version,
        )
        if not saved:
            raise WorkflowReviewError("stale_review_action")
        return updated

    async def recover_interrupted(self) -> int:
        """Fail incomplete checkpoints without replaying clinical input."""

        incomplete = await self.store.list_incomplete()
        for snapshot in incomplete:
            occurred_at = self.clock.now()
            transition = WorkflowTransition(
                from_status=snapshot.status,
                to_status=WorkflowStatus.FAILED,
                occurred_at=occurred_at,
                step=RECOVERY_STEP,
            )
            audit_event = AuditEvent(
                event_id=self.audit_event_ids.new(),
                workflow_id=snapshot.workflow_id,
                correlation_id=snapshot.correlation_id,
                event_type=AuditEventType.WORKFLOW_FAILED,
                occurred_at=occurred_at,
                actor_type=ActorType.SYSTEM,
                details={
                    "step": RECOVERY_STEP,
                    "from_status": snapshot.status.value,
                    "to_status": WorkflowStatus.FAILED.value,
                    "failure_code": INTERRUPTED_FAILURE_CODE,
                },
            )
            recovered = WorkflowRunSnapshot(
                workflow_id=snapshot.workflow_id,
                correlation_id=snapshot.correlation_id,
                trace_id=snapshot.trace_id,
                status=WorkflowStatus.FAILED,
                created_at=snapshot.created_at,
                updated_at=occurred_at,
                requires_human_review=snapshot.requires_human_review,
                guideline_evidence=snapshot.guideline_evidence,
                response_draft=snapshot.response_draft,
                review_citations=snapshot.review_citations,
                safety_result=snapshot.safety_result,
                post_generation_safety_result=snapshot.post_generation_safety_result,
                review_version=snapshot.review_version,
                review_record=snapshot.review_record,
                failure_code=INTERRUPTED_FAILURE_CODE,
                transitions=[*snapshot.transitions, transition],
                audit_log=[*snapshot.audit_log, audit_event],
            )
            await self.store.save(recovered)
        return len(incomplete)
