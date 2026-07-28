"""Graph state, reducer, and workflow transition semantics."""

from datetime import datetime
from typing import Annotated, TypedDict

from pydantic import ValidationError

from app.domain.clinical import PatientSummary
from app.domain.safety import SafetyResult
from app.domain.workflow import (
    Intent,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)

TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.FAILED,
    }
)
ALLOWED_WORKFLOW_TRANSITIONS: dict[
    WorkflowStatus,
    frozenset[WorkflowStatus],
] = {
    WorkflowStatus.QUEUED: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.FAILED,
        }
    ),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.PENDING_REVIEW,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.REJECTED,
            WorkflowStatus.FAILED,
        }
    ),
    WorkflowStatus.PENDING_REVIEW: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.REJECTED,
            WorkflowStatus.FAILED,
        }
    ),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.REJECTED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
}


class InvalidWorkflowTransition(ValueError):
    """A requested status transition violates workflow lifecycle rules."""


def append_transitions(
    current: list[WorkflowTransition],
    updates: list[WorkflowTransition],
) -> list[WorkflowTransition]:
    """Return a new append-only transition list without mutating inputs."""

    return [*current, *updates]


class WorkflowGraphState(TypedDict):
    """Mutable LangGraph state around the durable workflow contract."""

    workflow: WorkflowState
    transitions: Annotated[list[WorkflowTransition], append_transitions]


class WorkflowGraphUpdate(TypedDict, total=False):
    """Partial state update emitted by a workflow node."""

    workflow: WorkflowState
    transitions: list[WorkflowTransition]


def set_workflow_intent(
    workflow: WorkflowState,
    intent: Intent,
) -> WorkflowState:
    """Return a validated workflow copy with a structured intent."""

    values = workflow.model_dump()
    values["intent"] = intent
    return WorkflowState.model_validate(values)


def set_workflow_patient_data(
    workflow: WorkflowState,
    patient: PatientSummary,
) -> WorkflowState:
    """Return a validated workflow copy with normalized patient context."""

    values = workflow.model_dump()
    values["patient_data"] = patient
    return WorkflowState.model_validate(values)


def set_workflow_safety_result(
    workflow: WorkflowState,
    safety_result: SafetyResult,
) -> WorkflowState:
    """Return a validated workflow copy with a structured safety result."""

    values = workflow.model_dump()
    values.update(
        {
            "safety_result": safety_result,
            "requires_human_review": safety_result.requires_human_review,
        }
    )
    return WorkflowState.model_validate(values)


def transition_workflow(
    workflow: WorkflowState,
    to_status: WorkflowStatus,
    *,
    occurred_at: datetime,
    step: str,
    failure_code: str | None = None,
) -> tuple[WorkflowState, WorkflowTransition]:
    """Apply one validated, monotonic workflow status transition."""

    if to_status not in ALLOWED_WORKFLOW_TRANSITIONS[workflow.status]:
        raise InvalidWorkflowTransition(
            f"transition from {workflow.status} to {to_status} is not allowed"
        )
    if (to_status == WorkflowStatus.FAILED) != (failure_code is not None):
        raise InvalidWorkflowTransition(
            "failure_code must be set only when transitioning to failed"
        )

    try:
        transition = WorkflowTransition(
            from_status=workflow.status,
            to_status=to_status,
            occurred_at=occurred_at,
            step=step,
        )
    except ValidationError as error:
        raise InvalidWorkflowTransition(
            "workflow transition fields are invalid"
        ) from error
    if transition.occurred_at < workflow.updated_at:
        raise InvalidWorkflowTransition(
            "workflow transition timestamp must be monotonic"
        )

    updated_values = workflow.model_dump()
    updated_values.update(
        {
            "status": to_status,
            "updated_at": transition.occurred_at,
            "failure_code": failure_code,
        }
    )
    return WorkflowState.model_validate(updated_values), transition
