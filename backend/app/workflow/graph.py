"""Safely terminating Phase 2.1 LangGraph skeleton."""

import langsmith as ls
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.domain.workflow import (
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
)
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    WorkflowGraphState,
    WorkflowGraphUpdate,
    transition_workflow,
)

BEGIN_EXECUTION_NODE = "begin_execution"
HALT_UNIMPLEMENTED_NODE = "halt_unimplemented"
UNIMPLEMENTED_FAILURE_CODE = "workflow_not_implemented"

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


def build_workflow_graph() -> WorkflowCompiledGraph:
    """Compile the Phase 2.1 graph topology without external capabilities."""

    builder = StateGraph(
        state_schema=WorkflowGraphState,
        context_schema=WorkflowRuntime,
    )
    builder.add_node(BEGIN_EXECUTION_NODE, _begin_execution)
    builder.add_node(HALT_UNIMPLEMENTED_NODE, _halt_unimplemented)
    builder.add_edge(START, BEGIN_EXECUTION_NODE)
    builder.add_edge(BEGIN_EXECUTION_NODE, HALT_UNIMPLEMENTED_NODE)
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
