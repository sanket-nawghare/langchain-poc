"""Workflow-run creation, redacted checkpointing, and safe recovery."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.audit import ActorType, AuditEvent, AuditEventType
from app.domain.workflow import (
    WorkflowRunRequest,
    WorkflowRunSnapshot,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from app.tools.workflow_runs import WorkflowRunStore
from app.workflow.graph import execute_workflow
from app.workflow.runtime import AuditEventIdFactory, WorkflowClock, WorkflowRuntime

INTERRUPTED_FAILURE_CODE = "workflow_interrupted"
RECOVERY_STEP = "recover_interrupted"


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
                failure_code=INTERRUPTED_FAILURE_CODE,
                transitions=[*snapshot.transitions, transition],
                audit_log=[*snapshot.audit_log, audit_event],
            )
            await self.store.save(recovered)
        return len(incomplete)
