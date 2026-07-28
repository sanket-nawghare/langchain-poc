"""Phase 2.1 workflow transition and LangGraph skeleton tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import langsmith as ls
import pytest
from pydantic import ValidationError

from app.domain.workflow import (
    Intent,
    IntentClassification,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from app.services.deterministic_intent import DeterministicIntentClassifier
from app.tools.intent import IntentClassificationError, IntentClassifier
from app.workflow.graph import (
    BEGIN_EXECUTION_NODE,
    CLASSIFICATION_FAILURE_CODE,
    CLASSIFY_INTENT_NODE,
    HALT_UNIMPLEMENTED_NODE,
    REJECT_UNSUPPORTED_NODE,
    UNIMPLEMENTED_FAILURE_CODE,
    build_workflow_graph,
    execute_workflow_skeleton,
)
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    InvalidWorkflowTransition,
    append_transitions,
    transition_workflow,
)

WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
CORRELATION_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 7, 28, 9, 1, tzinfo=UTC)


@dataclass(frozen=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class FailingClassifier:
    async def classify(self, query: str) -> IntentClassification:
        raise IntentClassificationError("sensitive classifier failure")


class MalformedClassifier:
    async def classify(self, query: str) -> IntentClassification:
        return cast(
            IntentClassification,
            {"intent": "not-a-supported-intent"},
        )


def workflow_runtime(
    classifier: IntentClassifier | None = None,
) -> WorkflowRuntime:
    return WorkflowRuntime(
        clock=FixedClock(EXECUTED_AT),
        intent_classifier=classifier or DeterministicIntentClassifier(),
    )


def queued_workflow(
    query: str = "What precautions relate to this patient's conditions?",
) -> WorkflowState:
    return WorkflowState(
        workflow_id=WORKFLOW_ID,
        correlation_id=CORRELATION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        user_query=query,
        patient_id="synthetic-patient-1",
    )


def transition(
    from_status: WorkflowStatus,
    to_status: WorkflowStatus,
    *,
    step: str,
) -> WorkflowTransition:
    return WorkflowTransition(
        from_status=from_status,
        to_status=to_status,
        occurred_at=EXECUTED_AT,
        step=step,
    )


def test_transition_reducer_is_append_only_without_mutating_inputs() -> None:
    current = [
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            step="first",
        )
    ]
    updates = [
        transition(
            WorkflowStatus.RUNNING,
            WorkflowStatus.FAILED,
            step="second",
        )
    ]

    merged = append_transitions(current, updates)

    assert [item.step for item in merged] == ["first", "second"]
    assert [item.step for item in current] == ["first"]
    assert [item.step for item in updates] == ["second"]
    assert merged is not current
    assert merged is not updates


def test_applies_valid_transition_with_monotonic_timestamp() -> None:
    updated, recorded = transition_workflow(
        queued_workflow(),
        WorkflowStatus.RUNNING,
        occurred_at=EXECUTED_AT,
        step=BEGIN_EXECUTION_NODE,
    )

    assert updated.status == WorkflowStatus.RUNNING
    assert updated.updated_at == EXECUTED_AT
    assert updated.failure_code is None
    assert recorded.from_status == WorkflowStatus.QUEUED
    assert recorded.to_status == WorkflowStatus.RUNNING
    assert recorded.step == BEGIN_EXECUTION_NODE


@pytest.mark.parametrize(
    ("initial_status", "target_status"),
    [
        (WorkflowStatus.QUEUED, WorkflowStatus.COMPLETED),
        (WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING),
        (WorkflowStatus.REJECTED, WorkflowStatus.RUNNING),
        (WorkflowStatus.FAILED, WorkflowStatus.RUNNING),
    ],
)
def test_rejects_invalid_and_terminal_transitions(
    initial_status: WorkflowStatus,
    target_status: WorkflowStatus,
) -> None:
    values = queued_workflow().model_dump()
    values["status"] = initial_status
    if initial_status == WorkflowStatus.FAILED:
        values["failure_code"] = "already_failed"
    workflow = WorkflowState.model_validate(values)

    with pytest.raises(InvalidWorkflowTransition, match="not allowed"):
        transition_workflow(
            workflow,
            target_status,
            occurred_at=EXECUTED_AT,
            step="invalid_transition",
        )


def test_rejects_non_monotonic_or_naive_transition_time() -> None:
    with pytest.raises(InvalidWorkflowTransition, match="monotonic"):
        transition_workflow(
            queued_workflow(),
            WorkflowStatus.RUNNING,
            occurred_at=CREATED_AT - timedelta(seconds=1),
            step=BEGIN_EXECUTION_NODE,
        )

    with pytest.raises(InvalidWorkflowTransition, match="fields are invalid"):
        transition_workflow(
            queued_workflow(),
            WorkflowStatus.RUNNING,
            occurred_at=datetime(2026, 7, 28, 9, 1),
            step=BEGIN_EXECUTION_NODE,
        )


@pytest.mark.parametrize(
    ("target_status", "failure_code"),
    [
        (WorkflowStatus.FAILED, None),
        (WorkflowStatus.RUNNING, "unexpected_failure"),
    ],
)
def test_failure_code_matches_failed_transition(
    target_status: WorkflowStatus,
    failure_code: str | None,
) -> None:
    with pytest.raises(InvalidWorkflowTransition, match="failure_code"):
        transition_workflow(
            queued_workflow(),
            target_status,
            occurred_at=EXECUTED_AT,
            step="failure_code_check",
            failure_code=failure_code,
        )


def test_execution_result_rejects_broken_transition_history() -> None:
    failed_values = queued_workflow().model_dump()
    failed_values.update(
        {
            "status": WorkflowStatus.FAILED,
            "updated_at": EXECUTED_AT,
            "failure_code": "expected_failure",
        }
    )
    failed_workflow = WorkflowState.model_validate(failed_values)
    broken_history = [
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            step="first",
        ),
        transition(
            WorkflowStatus.QUEUED,
            WorkflowStatus.FAILED,
            step="broken",
        ),
    ]

    with pytest.raises(ValidationError, match="status chain"):
        WorkflowExecutionResult(
            workflow=failed_workflow,
            transitions=broken_history,
        )


def test_graph_has_only_the_reviewed_intent_routing_topology() -> None:
    graph = build_workflow_graph().get_graph()

    assert set(graph.nodes) == {
        "__start__",
        BEGIN_EXECUTION_NODE,
        CLASSIFY_INTENT_NODE,
        REJECT_UNSUPPORTED_NODE,
        HALT_UNIMPLEMENTED_NODE,
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", BEGIN_EXECUTION_NODE),
        (BEGIN_EXECUTION_NODE, CLASSIFY_INTENT_NODE),
        (CLASSIFY_INTENT_NODE, HALT_UNIMPLEMENTED_NODE),
        (CLASSIFY_INTENT_NODE, REJECT_UNSUPPORTED_NODE),
        (CLASSIFY_INTENT_NODE, "__end__"),
        (REJECT_UNSUPPORTED_NODE, "__end__"),
        (HALT_UNIMPLEMENTED_NODE, "__end__"),
    }


@pytest.mark.anyio
async def test_supported_intent_reaches_safe_unimplemented_stop() -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.intent == Intent.CLINICAL_QA
    assert result.workflow.failure_code == UNIMPLEMENTED_FAILURE_CODE
    assert result.workflow.updated_at == EXECUTED_AT
    assert [
        (item.from_status, item.to_status, item.step) for item in result.transitions
    ] == [
        (
            WorkflowStatus.QUEUED,
            WorkflowStatus.RUNNING,
            BEGIN_EXECUTION_NODE,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowStatus.FAILED,
            HALT_UNIMPLEMENTED_NODE,
        ),
    ]
    assert result.workflow.patient_data is None
    assert result.workflow.final_response is None
    assert result.workflow.audit_log == []


@pytest.mark.anyio
async def test_unknown_intent_is_rejected_without_reaching_clinical_path() -> None:
    result = await execute_workflow_skeleton(
        queued_workflow("Please schedule an appointment"),
        runtime=workflow_runtime(),
    )

    assert result.workflow.status == WorkflowStatus.REJECTED
    assert result.workflow.intent == Intent.UNKNOWN
    assert result.workflow.failure_code is None
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        REJECT_UNSUPPORTED_NODE,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "classifier",
    [FailingClassifier(), MalformedClassifier()],
)
async def test_classifier_failure_or_malformed_output_fails_safely(
    classifier: IntentClassifier,
) -> None:
    result = await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(classifier),
    )

    assert result.workflow.status == WorkflowStatus.FAILED
    assert result.workflow.intent == Intent.UNKNOWN
    assert result.workflow.failure_code == CLASSIFICATION_FAILURE_CODE
    assert [item.step for item in result.transitions] == [
        BEGIN_EXECUTION_NODE,
        CLASSIFY_INTENT_NODE,
    ]
    assert "sensitive" not in str(result.model_dump(mode="json"))


@pytest.mark.anyio
async def test_skeleton_replay_is_deterministic() -> None:
    runtime = workflow_runtime()

    first = await execute_workflow_skeleton(queued_workflow(), runtime=runtime)
    second = await execute_workflow_skeleton(queued_workflow(), runtime=runtime)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.anyio
async def test_skeleton_explicitly_disables_external_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracing_values: list[bool | None] = []

    @contextmanager
    def tracing_context(*, enabled: bool | None = None) -> Iterator[None]:
        tracing_values.append(enabled)
        yield

    monkeypatch.setattr(
        ls,
        "tracing_context",
        tracing_context,
    )

    await execute_workflow_skeleton(
        queued_workflow(),
        runtime=workflow_runtime(),
    )

    assert tracing_values == [False]
