"""Safely terminating Phase 2.1 LangGraph skeleton."""

from typing import Literal

import langsmith as ls
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domain.workflow import (
    Intent,
    IntentClassification,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
)
from app.tools.intent import IntentClassificationError
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    WorkflowGraphState,
    WorkflowGraphUpdate,
    set_workflow_intent,
    transition_workflow,
)

BEGIN_EXECUTION_NODE = "begin_execution"
CLASSIFY_INTENT_NODE = "classify_intent"
REJECT_UNSUPPORTED_NODE = "reject_unsupported"
HALT_UNIMPLEMENTED_NODE = "halt_unimplemented"
UNIMPLEMENTED_FAILURE_CODE = "workflow_not_implemented"
CLASSIFICATION_FAILURE_CODE = "intent_classification_failed"

type ClassificationRoute = Literal["supported", "unsupported", "failed"]

type WorkflowCompiledGraph = CompiledStateGraph[
    WorkflowGraphState,
    WorkflowRuntime,
    WorkflowGraphState,
    WorkflowGraphState,
]


async def _begin_execution(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow, transition = transition_workflow(
        state["workflow"],
        WorkflowStatus.RUNNING,
        occurred_at=runtime.context.clock.now(),
        step=BEGIN_EXECUTION_NODE,
    )
    return {"workflow": workflow, "transitions": [transition]}


async def _halt_unimplemented(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow, transition = transition_workflow(
        state["workflow"],
        WorkflowStatus.FAILED,
        occurred_at=runtime.context.clock.now(),
        step=HALT_UNIMPLEMENTED_NODE,
        failure_code=UNIMPLEMENTED_FAILURE_CODE,
    )
    return {"workflow": workflow, "transitions": [transition]}


async def _classify_intent(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    try:
        raw_result = await runtime.context.intent_classifier.classify(
            workflow.user_query
        )
        raw_payload = (
            raw_result.model_dump()
            if isinstance(raw_result, IntentClassification)
            else raw_result
        )
        classification = IntentClassification.model_validate(raw_payload)
        classified_workflow = set_workflow_intent(workflow, classification.intent)
    except (IntentClassificationError, ValidationError):
        failed_workflow, transition = transition_workflow(
            workflow,
            WorkflowStatus.FAILED,
            occurred_at=runtime.context.clock.now(),
            step=CLASSIFY_INTENT_NODE,
            failure_code=CLASSIFICATION_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    return {"workflow": classified_workflow}


async def _reject_unsupported(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow, transition = transition_workflow(
        state["workflow"],
        WorkflowStatus.REJECTED,
        occurred_at=runtime.context.clock.now(),
        step=REJECT_UNSUPPORTED_NODE,
    )
    return {"workflow": workflow, "transitions": [transition]}


async def _route_classification(
    state: WorkflowGraphState,
) -> ClassificationRoute:
    workflow = state["workflow"]
    if workflow.status == WorkflowStatus.FAILED:
        return "failed"
    if workflow.intent == Intent.CLINICAL_QA:
        return "supported"
    return "unsupported"


def build_workflow_graph() -> WorkflowCompiledGraph:
    """Compile deterministic intent routing without clinical data access."""

    builder = StateGraph(
        state_schema=WorkflowGraphState,
        context_schema=WorkflowRuntime,
    )
    builder.add_node(BEGIN_EXECUTION_NODE, _begin_execution)
    builder.add_node(CLASSIFY_INTENT_NODE, _classify_intent)
    builder.add_node(REJECT_UNSUPPORTED_NODE, _reject_unsupported)
    builder.add_node(HALT_UNIMPLEMENTED_NODE, _halt_unimplemented)
    builder.add_edge(START, BEGIN_EXECUTION_NODE)
    builder.add_edge(BEGIN_EXECUTION_NODE, CLASSIFY_INTENT_NODE)
    builder.add_conditional_edges(
        CLASSIFY_INTENT_NODE,
        _route_classification,
        {
            "supported": HALT_UNIMPLEMENTED_NODE,
            "unsupported": REJECT_UNSUPPORTED_NODE,
            "failed": END,
        },
    )
    builder.add_edge(REJECT_UNSUPPORTED_NODE, END)
    builder.add_edge(HALT_UNIMPLEMENTED_NODE, END)
    return builder.compile()


WORKFLOW_GRAPH = build_workflow_graph()


async def execute_workflow_skeleton(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> WorkflowExecutionResult:
    """Execute the skeleton and validate its provider-neutral result."""

    with ls.tracing_context(enabled=False):
        result = await WORKFLOW_GRAPH.ainvoke(
            {"workflow": workflow, "transitions": []},
            context=runtime,
        )
    return WorkflowExecutionResult.model_validate(result)
