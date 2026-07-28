"""Safely terminating Phase 2.1 LangGraph skeleton."""

from typing import Literal

import langsmith as ls
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domain.clinical import PatientSummary
from app.domain.safety import SafetyDecision, SafetyResult
from app.domain.workflow import (
    Intent,
    IntentClassification,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
)
from app.tools.fhir import (
    FhirClientError,
    FhirNotFoundError,
    FhirRequestError,
    FhirResponseError,
    FhirTimeoutError,
    FhirUnavailableError,
)
from app.tools.intent import IntentClassificationError
from app.tools.patient import PatientSummaryError
from app.tools.safety import SafetyPolicyError
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    WorkflowGraphState,
    WorkflowGraphUpdate,
    set_workflow_intent,
    set_workflow_patient_data,
    set_workflow_safety_result,
    transition_workflow,
)

BEGIN_EXECUTION_NODE = "begin_execution"
CLASSIFY_INTENT_NODE = "classify_intent"
REJECT_UNSUPPORTED_NODE = "reject_unsupported"
RETRIEVE_PATIENT_NODE = "retrieve_patient"
SAFETY_PRECHECK_NODE = "safety_precheck"
HALT_UNIMPLEMENTED_NODE = "halt_unimplemented"
UNIMPLEMENTED_FAILURE_CODE = "workflow_not_implemented"
CLASSIFICATION_FAILURE_CODE = "intent_classification_failed"
INVALID_PATIENT_SUMMARY_CODE = "invalid_patient_summary"
SAFETY_FAILURE_CODE = "safety_evaluation_failed"

type ClassificationRoute = Literal["supported", "unsupported", "failed"]
type RetrievalRoute = Literal["retrieved", "failed"]
type SafetyRoute = Literal["pass", "review", "block", "failed"]

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


def _fhir_failure_code(error: FhirClientError) -> str:
    if isinstance(error, FhirNotFoundError):
        return "patient_not_found"
    if isinstance(error, FhirRequestError):
        return "invalid_patient_id"
    if isinstance(error, FhirTimeoutError):
        return "fhir_timeout"
    if isinstance(error, FhirUnavailableError):
        return "fhir_unavailable"
    if isinstance(error, FhirResponseError):
        return "invalid_fhir_response"
    return "fhir_request_failed"


async def _retrieve_patient(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    try:
        raw_summary = await runtime.context.patient_summary_reader.get(
            workflow.patient_id
        )
        raw_payload = (
            raw_summary.model_dump()
            if isinstance(raw_summary, PatientSummary)
            else raw_summary
        )
        summary = PatientSummary.model_validate(raw_payload)
        if summary.patient_id != workflow.patient_id:
            raise PatientSummaryError("patient summary ID does not match workflow")
        updated_workflow = set_workflow_patient_data(workflow, summary)
    except FhirClientError as error:
        failed_workflow, transition = transition_workflow(
            workflow,
            WorkflowStatus.FAILED,
            occurred_at=runtime.context.clock.now(),
            step=RETRIEVE_PATIENT_NODE,
            failure_code=_fhir_failure_code(error),
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (PatientSummaryError, ValidationError):
        failed_workflow, transition = transition_workflow(
            workflow,
            WorkflowStatus.FAILED,
            occurred_at=runtime.context.clock.now(),
            step=RETRIEVE_PATIENT_NODE,
            failure_code=INVALID_PATIENT_SUMMARY_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    return {"workflow": updated_workflow}


async def _safety_precheck(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    if workflow.patient_data is None:
        raise AssertionError("safety pre-check requires patient data")
    try:
        raw_result = await runtime.context.safety_policy.evaluate(
            query=workflow.user_query,
            patient=workflow.patient_data,
        )
        raw_payload = (
            raw_result.model_dump()
            if isinstance(raw_result, SafetyResult)
            else raw_result
        )
        safety_result = SafetyResult.model_validate(raw_payload)
        updated_workflow = set_workflow_safety_result(
            workflow,
            safety_result,
        )
    except (SafetyPolicyError, ValidationError):
        failed_workflow, transition = transition_workflow(
            workflow,
            WorkflowStatus.FAILED,
            occurred_at=runtime.context.clock.now(),
            step=SAFETY_PRECHECK_NODE,
            failure_code=SAFETY_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}

    if safety_result.decision == SafetyDecision.REVIEW:
        reviewed_workflow, transition = transition_workflow(
            updated_workflow,
            WorkflowStatus.PENDING_REVIEW,
            occurred_at=runtime.context.clock.now(),
            step=SAFETY_PRECHECK_NODE,
        )
        return {"workflow": reviewed_workflow, "transitions": [transition]}
    if safety_result.decision == SafetyDecision.BLOCK:
        blocked_workflow, transition = transition_workflow(
            updated_workflow,
            WorkflowStatus.REJECTED,
            occurred_at=runtime.context.clock.now(),
            step=SAFETY_PRECHECK_NODE,
        )
        return {"workflow": blocked_workflow, "transitions": [transition]}
    return {"workflow": updated_workflow}


async def _route_classification(
    state: WorkflowGraphState,
) -> ClassificationRoute:
    workflow = state["workflow"]
    if workflow.status == WorkflowStatus.FAILED:
        return "failed"
    if workflow.intent == Intent.CLINICAL_QA:
        return "supported"
    return "unsupported"


async def _route_retrieval(state: WorkflowGraphState) -> RetrievalRoute:
    return (
        "failed" if state["workflow"].status == WorkflowStatus.FAILED else "retrieved"
    )


async def _route_safety(state: WorkflowGraphState) -> SafetyRoute:
    workflow = state["workflow"]
    if workflow.status == WorkflowStatus.FAILED:
        return "failed"
    if workflow.status == WorkflowStatus.PENDING_REVIEW:
        return "review"
    if workflow.status == WorkflowStatus.REJECTED:
        return "block"
    return "pass"


def build_workflow_graph() -> WorkflowCompiledGraph:
    """Compile deterministic intent, patient, and safety routing."""

    builder = StateGraph(
        state_schema=WorkflowGraphState,
        context_schema=WorkflowRuntime,
    )
    builder.add_node(BEGIN_EXECUTION_NODE, _begin_execution)
    builder.add_node(CLASSIFY_INTENT_NODE, _classify_intent)
    builder.add_node(REJECT_UNSUPPORTED_NODE, _reject_unsupported)
    builder.add_node(RETRIEVE_PATIENT_NODE, _retrieve_patient)
    builder.add_node(SAFETY_PRECHECK_NODE, _safety_precheck)
    builder.add_node(HALT_UNIMPLEMENTED_NODE, _halt_unimplemented)
    builder.add_edge(START, BEGIN_EXECUTION_NODE)
    builder.add_edge(BEGIN_EXECUTION_NODE, CLASSIFY_INTENT_NODE)
    builder.add_conditional_edges(
        CLASSIFY_INTENT_NODE,
        _route_classification,
        {
            "supported": RETRIEVE_PATIENT_NODE,
            "unsupported": REJECT_UNSUPPORTED_NODE,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        RETRIEVE_PATIENT_NODE,
        _route_retrieval,
        {
            "retrieved": SAFETY_PRECHECK_NODE,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        SAFETY_PRECHECK_NODE,
        _route_safety,
        {
            "pass": HALT_UNIMPLEMENTED_NODE,
            "review": END,
            "block": END,
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
