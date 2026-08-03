"""Provider-neutral clinical workflow graph."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import langsmith as ls
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domain.audit import ActorType, AuditEvent, AuditEventType, AuditValue
from app.domain.clinical import PatientSummary
from app.domain.guidelines import (
    EvidenceAssessment,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
)
from app.domain.safety import SafetyDecision, SafetyResult
from app.domain.workflow import (
    GeneratedResponse,
    Intent,
    IntentClassification,
    ResponseDraft,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from app.rag.retrieval import (
    GuidelineRetrievalError,
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
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
from app.tools.response import (
    ResponseGenerationError,
    ResponseGenerationTimeoutError,
)
from app.tools.safety import SafetyPolicyError
from app.workflow.runtime import WorkflowRuntime
from app.workflow.state import (
    WorkflowGraphState,
    WorkflowGraphUpdate,
    append_workflow_audit_events,
    set_workflow_guideline_evidence,
    set_workflow_intent,
    set_workflow_patient_data,
    set_workflow_safety_result,
    transition_workflow,
)

BEGIN_EXECUTION_NODE = "begin_execution"
CLASSIFY_INTENT_NODE = "classify_intent"
REJECT_UNSUPPORTED_NODE = "reject_unsupported"
RETRIEVE_PATIENT_NODE = "retrieve_patient"
RETRIEVE_GUIDELINES_NODE = "retrieve_guidelines"
SAFETY_PRECHECK_NODE = "safety_precheck"
GENERATE_RESPONSE_NODE = "generate_response"
CLASSIFICATION_FAILURE_CODE = "intent_classification_failed"
CLASSIFICATION_TIMEOUT_CODE = "intent_classification_timeout"
INVALID_PATIENT_SUMMARY_CODE = "invalid_patient_summary"
SAFETY_FAILURE_CODE = "safety_evaluation_failed"
RESPONSE_FAILURE_CODE = "response_generation_failed"
RESPONSE_TIMEOUT_CODE = "response_generation_timeout"
GUIDELINE_EVIDENCE_UNAVAILABLE_CODE = "guideline_evidence_not_available"
GUIDELINE_RETRIEVAL_TIMEOUT_CODE = "guideline_retrieval_timeout"
GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE = "guideline_retrieval_unavailable"
INVALID_GUIDELINE_EVIDENCE_CODE = "invalid_guideline_evidence"
EDUCATIONAL_DISCLAIMER = (
    "Educational demonstration using synthetic data only. This response is not "
    "medical advice and must not replace evaluation by a qualified healthcare "
    "professional."
)

type ClassificationRoute = Literal["supported", "unsupported", "failed"]
type RetrievalRoute = Literal["retrieved", "failed"]
type GuidelineRetrievalRoute = Literal["continue", "review", "failed"]
type SafetyRoute = Literal["pass", "review", "block", "failed"]

type WorkflowCompiledGraph = CompiledStateGraph[
    WorkflowGraphState,
    WorkflowRuntime,
    WorkflowGraphState,
    WorkflowGraphState,
]


class WorkflowNodeTimeoutError(TimeoutError):
    """A workflow capability exhausted its bounded attempts."""


async def _run_bounded[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    runtime: Runtime[WorkflowRuntime],
    *,
    retryable: tuple[type[Exception], ...],
) -> ResultT:
    policy = runtime.context.execution_policy
    for attempt in range(policy.max_retries + 1):
        try:
            return await asyncio.wait_for(
                operation(),
                timeout=policy.timeout_seconds,
            )
        except TimeoutError as error:
            if attempt == policy.max_retries:
                raise WorkflowNodeTimeoutError from error
        except retryable:
            if attempt == policy.max_retries:
                raise
    raise AssertionError("bounded workflow operation exhausted without an outcome")


def _audit_event(
    workflow: WorkflowState,
    runtime: Runtime[WorkflowRuntime],
    event_type: AuditEventType,
    *,
    details: dict[str, AuditValue],
) -> AuditEvent:
    return AuditEvent(
        event_id=runtime.context.audit_event_ids.new(),
        workflow_id=workflow.workflow_id,
        correlation_id=workflow.correlation_id,
        event_type=event_type,
        occurred_at=runtime.context.clock.now(),
        actor_type=ActorType.SYSTEM,
        details=details,
    )


def _transition_with_audit(
    workflow: WorkflowState,
    runtime: Runtime[WorkflowRuntime],
    to_status: WorkflowStatus,
    *,
    step: str,
    failure_code: str | None = None,
) -> tuple[WorkflowState, WorkflowTransition]:
    updated, transition = transition_workflow(
        workflow,
        to_status,
        occurred_at=runtime.context.clock.now(),
        step=step,
        failure_code=failure_code,
    )
    audited = append_workflow_audit_events(
        updated,
        [
            _status_audit_event(
                updated,
                runtime,
                from_status=workflow.status,
                step=step,
                failure_code=failure_code,
            )
        ],
    )
    return audited, transition


def _status_audit_event(
    workflow: WorkflowState,
    runtime: Runtime[WorkflowRuntime],
    *,
    from_status: WorkflowStatus,
    step: str,
    failure_code: str | None = None,
) -> AuditEvent:
    details: dict[str, AuditValue] = {
        "step": step,
        "from_status": from_status.value,
        "to_status": workflow.status.value,
    }
    if failure_code is not None:
        details["failure_code"] = failure_code
    event_type = (
        AuditEventType.WORKFLOW_FAILED
        if workflow.status == WorkflowStatus.FAILED
        else AuditEventType.STATUS_CHANGED
    )
    return _audit_event(workflow, runtime, event_type, details=details)


async def _begin_execution(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow, transition = _transition_with_audit(
        state["workflow"],
        runtime,
        WorkflowStatus.RUNNING,
        step=BEGIN_EXECUTION_NODE,
    )
    return {"workflow": workflow, "transitions": [transition]}


async def _classify_intent(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    try:
        raw_result = await _run_bounded(
            lambda: runtime.context.intent_classifier.classify(workflow.user_query),
            runtime,
            retryable=(IntentClassificationError,),
        )
        raw_payload = (
            raw_result.model_dump()
            if isinstance(raw_result, IntentClassification)
            else raw_result
        )
        classification = IntentClassification.model_validate(raw_payload)
        classified_workflow = set_workflow_intent(workflow, classification.intent)
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=CLASSIFY_INTENT_NODE,
            failure_code=CLASSIFICATION_TIMEOUT_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (IntentClassificationError, ValidationError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=CLASSIFY_INTENT_NODE,
            failure_code=CLASSIFICATION_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=CLASSIFY_INTENT_NODE,
            failure_code=CLASSIFICATION_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    audited_workflow = append_workflow_audit_events(
        classified_workflow,
        [
            _audit_event(
                classified_workflow,
                runtime,
                AuditEventType.TOOL_CALLED,
                details={
                    "tool": "intent_classifier",
                    "outcome": "success",
                    "intent": classification.intent.value,
                },
            )
        ],
    )
    return {"workflow": audited_workflow}


async def _reject_unsupported(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow, transition = _transition_with_audit(
        state["workflow"],
        runtime,
        WorkflowStatus.REJECTED,
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
        raw_summary = await _run_bounded(
            lambda: runtime.context.patient_summary_reader.get(workflow.patient_id),
            runtime,
            retryable=(FhirTimeoutError, FhirUnavailableError),
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
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_PATIENT_NODE,
            failure_code="fhir_timeout",
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except FhirClientError as error:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_PATIENT_NODE,
            failure_code=_fhir_failure_code(error),
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (PatientSummaryError, ValidationError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_PATIENT_NODE,
            failure_code=INVALID_PATIENT_SUMMARY_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_PATIENT_NODE,
            failure_code="fhir_request_failed",
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    audited_workflow = append_workflow_audit_events(
        updated_workflow,
        [
            _audit_event(
                updated_workflow,
                runtime,
                AuditEventType.TOOL_CALLED,
                details={
                    "tool": "patient_summary_reader",
                    "outcome": "success",
                    "truncated": bool(summary.truncated_categories),
                },
            )
        ],
    )
    return {"workflow": audited_workflow}


def _guideline_failure_code(error: GuidelineRetrievalError) -> str:
    if isinstance(error, GuidelineRetrievalTimeoutError):
        return GUIDELINE_RETRIEVAL_TIMEOUT_CODE
    if isinstance(error, GuidelineRetrievalUnavailableError):
        return GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE
    return INVALID_GUIDELINE_EVIDENCE_CODE


def _deidentified_guideline_query(workflow: WorkflowState) -> str:
    """Reject known patient identifiers before querying the guideline index."""

    normalized_query = workflow.user_query.casefold()
    patient = workflow.patient_data
    forbidden_values = [workflow.patient_id]
    if patient is not None and patient.display_name is not None:
        forbidden_values.append(patient.display_name)
    if any(value.casefold() in normalized_query for value in forbidden_values):
        raise GuidelineRetrievalResponseError(
            "guideline query contains a known patient identifier"
        )
    return workflow.user_query


async def _retrieve_guidelines(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    retriever = runtime.context.guideline_retriever
    if retriever is None:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_GUIDELINES_NODE,
            failure_code=GUIDELINE_RETRIEVAL_UNAVAILABLE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}

    try:
        request = GuidelineRetrievalRequest(
            clinical_query=_deidentified_guideline_query(workflow),
            as_of=runtime.context.clock.now().date(),
        )
        raw_result = await _run_bounded(
            lambda: retriever.retrieve(request),
            runtime,
            retryable=(
                GuidelineRetrievalTimeoutError,
                GuidelineRetrievalUnavailableError,
            ),
        )
        raw_payload = (
            raw_result.model_dump()
            if isinstance(raw_result, GuidelineRetrievalResult)
            else raw_result
        )
        result = GuidelineRetrievalResult.model_validate(raw_payload)
        updated_workflow = set_workflow_guideline_evidence(workflow, result)
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_GUIDELINES_NODE,
            failure_code=GUIDELINE_RETRIEVAL_TIMEOUT_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except GuidelineRetrievalError as error:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_GUIDELINES_NODE,
            failure_code=_guideline_failure_code(error),
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except ValidationError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_GUIDELINES_NODE,
            failure_code=INVALID_GUIDELINE_EVIDENCE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=RETRIEVE_GUIDELINES_NODE,
            failure_code=INVALID_GUIDELINE_EVIDENCE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}

    evidence = updated_workflow.guideline_evidence
    if evidence is None:
        raise AssertionError("retrieval projection requires evidence metadata")
    details: dict[str, AuditValue] = {
        "tool": "guideline_retriever",
        "outcome": "success",
        "assessment": evidence.assessment.value,
        "policy_version": evidence.policy_version,
        "match_count": evidence.match_count,
    }
    if evidence.document_ids:
        details["document_ids"] = ",".join(evidence.document_ids)
        details["chunk_ids"] = ",".join(evidence.chunk_ids)
    audited_workflow = append_workflow_audit_events(
        updated_workflow,
        [
            _audit_event(
                updated_workflow,
                runtime,
                AuditEventType.TOOL_CALLED,
                details=details,
            )
        ],
    )
    if evidence.assessment in {
        EvidenceAssessment.INSUFFICIENT,
        EvidenceAssessment.CONFLICTING,
    }:
        reviewed_values = audited_workflow.model_dump()
        reviewed_values["requires_human_review"] = True
        reviewed_workflow = WorkflowState.model_validate(reviewed_values)
        reviewed_workflow, transition = _transition_with_audit(
            reviewed_workflow,
            runtime,
            WorkflowStatus.PENDING_REVIEW,
            step=RETRIEVE_GUIDELINES_NODE,
        )
        return {"workflow": reviewed_workflow, "transitions": [transition]}
    return {"workflow": audited_workflow}


async def _safety_precheck(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    patient = workflow.patient_data
    if patient is None:
        raise AssertionError("safety pre-check requires patient data")
    try:
        raw_result = await _run_bounded(
            lambda: runtime.context.safety_policy.evaluate(
                query=workflow.user_query,
                patient=patient,
            ),
            runtime,
            retryable=(SafetyPolicyError,),
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
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=SAFETY_PRECHECK_NODE,
            failure_code="safety_evaluation_timeout",
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (SafetyPolicyError, ValidationError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=SAFETY_PRECHECK_NODE,
            failure_code=SAFETY_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=SAFETY_PRECHECK_NODE,
            failure_code=SAFETY_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}

    audited_workflow = append_workflow_audit_events(
        updated_workflow,
        [
            _audit_event(
                updated_workflow,
                runtime,
                AuditEventType.SAFETY_EVALUATED,
                details={
                    "decision": safety_result.decision.value,
                    "policy_version": safety_result.policy_version,
                    "reason_count": len(safety_result.reasons),
                },
            )
        ],
    )
    if safety_result.decision == SafetyDecision.REVIEW:
        reviewed_workflow, transition = _transition_with_audit(
            audited_workflow,
            runtime,
            WorkflowStatus.PENDING_REVIEW,
            step=SAFETY_PRECHECK_NODE,
        )
        return {"workflow": reviewed_workflow, "transitions": [transition]}
    if safety_result.decision == SafetyDecision.BLOCK:
        blocked_workflow, transition = _transition_with_audit(
            audited_workflow,
            runtime,
            WorkflowStatus.REJECTED,
            step=SAFETY_PRECHECK_NODE,
        )
        return {"workflow": blocked_workflow, "transitions": [transition]}
    return {"workflow": audited_workflow}


async def _generate_response(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    patient = workflow.patient_data
    if patient is None or workflow.safety_result is None:
        raise AssertionError("response generation requires patient and safety results")
    evidence = workflow.guideline_evidence
    if (
        evidence is None
        or evidence.assessment is not EvidenceAssessment.SUFFICIENT
        or not workflow.retrieved_guidelines
    ):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=GUIDELINE_EVIDENCE_UNAVAILABLE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    try:
        raw_draft = await _run_bounded(
            lambda: runtime.context.response_generator.generate(
                query=workflow.user_query,
                patient=patient,
                guidelines=workflow.retrieved_guidelines,
            ),
            runtime,
            retryable=(ResponseGenerationError,),
        )
        raw_payload = (
            raw_draft.model_dump()
            if isinstance(raw_draft, ResponseDraft)
            else raw_draft
        )
        draft = ResponseDraft.model_validate(raw_payload)
        response = GeneratedResponse(
            answer=draft.answer,
            citations=workflow.retrieved_guidelines,
            disclaimer=EDUCATIONAL_DISCLAIMER,
        )
    except (WorkflowNodeTimeoutError, ResponseGenerationTimeoutError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=RESPONSE_TIMEOUT_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (ResponseGenerationError, ValidationError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=RESPONSE_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=RESPONSE_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}

    completed_workflow, transition = transition_workflow(
        workflow,
        WorkflowStatus.COMPLETED,
        occurred_at=runtime.context.clock.now(),
        step=GENERATE_RESPONSE_NODE,
        final_response=response,
    )
    audited_workflow = append_workflow_audit_events(
        completed_workflow,
        [
            _audit_event(
                completed_workflow,
                runtime,
                AuditEventType.RESPONSE_GENERATED,
                details={
                    "generator": "response_generator",
                    "outcome": "success",
                    "citation_count": len(response.citations),
                },
            ),
            _status_audit_event(
                completed_workflow,
                runtime,
                from_status=workflow.status,
                step=GENERATE_RESPONSE_NODE,
            ),
        ],
    )
    return {"workflow": audited_workflow, "transitions": [transition]}


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


async def _route_guideline_retrieval(
    state: WorkflowGraphState,
) -> GuidelineRetrievalRoute:
    workflow = state["workflow"]
    if workflow.status == WorkflowStatus.FAILED:
        return "failed"
    if workflow.status == WorkflowStatus.PENDING_REVIEW:
        return "review"
    return "continue"


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
    """Compile deterministic routing through a qualified response."""

    builder = StateGraph(
        state_schema=WorkflowGraphState,
        context_schema=WorkflowRuntime,
    )
    builder.add_node(BEGIN_EXECUTION_NODE, _begin_execution)
    builder.add_node(CLASSIFY_INTENT_NODE, _classify_intent)
    builder.add_node(REJECT_UNSUPPORTED_NODE, _reject_unsupported)
    builder.add_node(RETRIEVE_PATIENT_NODE, _retrieve_patient)
    builder.add_node(RETRIEVE_GUIDELINES_NODE, _retrieve_guidelines)
    builder.add_node(SAFETY_PRECHECK_NODE, _safety_precheck)
    builder.add_node(GENERATE_RESPONSE_NODE, _generate_response)
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
            "retrieved": RETRIEVE_GUIDELINES_NODE,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        RETRIEVE_GUIDELINES_NODE,
        _route_guideline_retrieval,
        {
            "continue": SAFETY_PRECHECK_NODE,
            "review": END,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        SAFETY_PRECHECK_NODE,
        _route_safety,
        {
            "pass": GENERATE_RESPONSE_NODE,
            "review": END,
            "block": END,
            "failed": END,
        },
    )
    builder.add_edge(REJECT_UNSUPPORTED_NODE, END)
    builder.add_edge(GENERATE_RESPONSE_NODE, END)
    return builder.compile()


WORKFLOW_GRAPH = build_workflow_graph()


async def execute_workflow(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> WorkflowExecutionResult:
    """Execute the workflow and validate its provider-neutral result."""

    with ls.tracing_context(enabled=False):
        result = await WORKFLOW_GRAPH.ainvoke(
            {"workflow": workflow, "transitions": []},
            context=runtime,
        )
    return WorkflowExecutionResult.model_validate(result)


async def execute_workflow_skeleton(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> WorkflowExecutionResult:
    """Backward-compatible name retained for callers from sub-phase 2.1."""

    return await execute_workflow(workflow, runtime=runtime)
