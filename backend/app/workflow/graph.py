"""Provider-neutral clinical workflow graph."""

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import langsmith as ls
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domain.audit import ActorType, AuditEvent, AuditEventType, AuditValue
from app.domain.clinical import Citation, ClinicalRecordSummary, PatientSummary
from app.domain.generation import ResponseGenerationResult
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
from app.services.grounded_generation import build_grounded_generation_request
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
    ResponseGenerationAuthenticationError,
    ResponseGenerationContextLimitError,
    ResponseGenerationError,
    ResponseGenerationInputError,
    ResponseGenerationMalformedOutputError,
    ResponseGenerationRateLimitError,
    ResponseGenerationRefusalError,
    ResponseGenerationTimeoutError,
    ResponseGenerationUnavailableError,
)
from app.tools.safety import SafetyPolicyError
from app.workflow.runtime import WorkflowExecutionPolicy, WorkflowRuntime
from app.workflow.state import (
    WorkflowGraphState,
    WorkflowGraphUpdate,
    append_workflow_audit_events,
    set_workflow_guideline_evidence,
    set_workflow_intent,
    set_workflow_patient_data,
    set_workflow_post_generation_safety_result,
    set_workflow_response_draft,
    set_workflow_safety_result,
    transition_workflow,
)

BEGIN_EXECUTION_NODE = "begin_execution"
CLASSIFY_INTENT_NODE = "classify_intent"
REJECT_UNSUPPORTED_NODE = "reject_unsupported"
RETRIEVE_PATIENT_NODE = "retrieve_patient"
RETRIEVE_GUIDELINES_NODE = "retrieve_guidelines"
SAFETY_PRECHECK_NODE = "safety_precheck"
FINALIZE_PATIENT_SUMMARY_NODE = "finalize_patient_summary"
GENERATE_RESPONSE_NODE = "generate_response"
POST_GENERATION_SAFETY_NODE = "post_generation_safety"
FINALIZE_RESPONSE_NODE = "finalize_response"
CLASSIFICATION_FAILURE_CODE = "intent_classification_failed"
CLASSIFICATION_TIMEOUT_CODE = "intent_classification_timeout"
INVALID_PATIENT_SUMMARY_CODE = "invalid_patient_summary"
SAFETY_FAILURE_CODE = "safety_evaluation_failed"
POST_GENERATION_SAFETY_FAILURE_CODE = "post_generation_safety_evaluation_failed"
POST_GENERATION_SAFETY_TIMEOUT_CODE = "post_generation_safety_evaluation_timeout"
RESPONSE_FAILURE_CODE = "response_generation_failed"
RESPONSE_TIMEOUT_CODE = "response_generation_timeout"
RESPONSE_AUTHENTICATION_CODE = "response_generation_authentication_failed"
RESPONSE_RATE_LIMIT_CODE = "response_generation_rate_limited"
RESPONSE_UNAVAILABLE_CODE = "response_generation_unavailable"
RESPONSE_CONTEXT_LIMIT_CODE = "response_generation_context_limit"
RESPONSE_REFUSAL_CODE = "response_generation_refused"
RESPONSE_INVALID_INPUT_CODE = "response_generation_invalid_input"
RESPONSE_INVALID_OUTPUT_CODE = "response_generation_invalid_output"
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
type RetrievalRoute = Literal["patient_summary", "guidelines", "failed"]
type GuidelineRetrievalRoute = Literal["continue", "review", "failed"]
type SafetyRoute = Literal["patient_summary", "pass", "review", "block", "failed"]
type GenerationRoute = Literal["generated", "failed"]
type WorkflowEventPhase = Literal["started", "completed"]


@dataclass(frozen=True)
class WorkflowGraphEvent:
    """One safe node lifecycle event with state only after completion."""

    node: str
    phase: WorkflowEventPhase
    result: WorkflowExecutionResult | None = None


type WorkflowCompiledGraph = CompiledStateGraph[
    WorkflowGraphState,
    WorkflowRuntime,
    WorkflowGraphState,
    WorkflowGraphState,
]


class WorkflowNodeTimeoutError(TimeoutError):
    """A workflow capability exhausted its bounded attempts."""


PATIENT_SUMMARY_SOURCE_URL = (
    "http://localhost:8000/api/v1/evidence/synthetic-patient-summary"
)
ALLERGY_QUERY_PATTERN = re.compile(r"\ballerg(?:y|ies|ic)\b", re.IGNORECASE)
HISTORY_QUERY_PATTERN = re.compile(
    r"\b("
    r"current|currently|present|active|history|histories|summary|summaries|"
    r"summarize|summarise|list|lists|show|shows|"
    r"have|has|had|known|recorded|for\s+this\s+patient|of\s+the\s+patient"
    r")\b",
    re.IGNORECASE,
)


async def _run_bounded[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    runtime: Runtime[WorkflowRuntime],
    *,
    retryable: tuple[type[Exception], ...],
    policy: WorkflowExecutionPolicy | None = None,
) -> ResultT:
    selected_policy = policy or runtime.context.execution_policy
    for attempt in range(selected_policy.max_retries + 1):
        try:
            return await asyncio.wait_for(
                operation(),
                timeout=selected_policy.timeout_seconds,
            )
        except TimeoutError as error:
            if attempt == selected_policy.max_retries:
                raise WorkflowNodeTimeoutError from error
        except retryable:
            if attempt == selected_policy.max_retries:
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
    failure_reason: str | None = None,
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
                failure_reason=failure_reason,
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
    failure_reason: str | None = None,
) -> AuditEvent:
    details: dict[str, AuditValue] = {
        "step": step,
        "from_status": from_status.value,
        "to_status": workflow.status.value,
    }
    if failure_code is not None:
        details["failure_code"] = failure_code
    if failure_reason is not None:
        details["failure_reason"] = failure_reason
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


def _is_allergy_history_query(query: str) -> bool:
    """Return whether the request asks for allergy history from patient data."""

    return bool(ALLERGY_QUERY_PATTERN.search(query)) and bool(
        HISTORY_QUERY_PATTERN.search(query)
    )


def _allergy_record_summary(record: ClinicalRecordSummary) -> str:
    parts = [record.display]
    if record.status is not None:
        parts.append(f"status: {record.status}")
    if record.effective_at is not None:
        parts.append(f"recorded/effective: {record.effective_at}")
    if record.value is not None:
        parts.append(f"value: {record.value}")
    return "; ".join(parts)


def _patient_summary_citation(*, category: str, excerpt: str) -> Citation:
    return Citation(
        document_id="synthetic-patient-summary",
        chunk_id=f"patient-summary.{category}",
        title=f"Synthetic patient {category.replace('_', ' ')} summary",
        publisher="Local FHIR patient summary",
        source_url=PATIENT_SUMMARY_SOURCE_URL,
        excerpt=excerpt,
    )


def _allergy_history_response(patient: PatientSummary) -> GeneratedResponse:
    if patient.allergies:
        allergy_lines = [
            f"{index}. {_allergy_record_summary(allergy)}"
            for index, allergy in enumerate(patient.allergies, start=1)
        ]
        answer = (
            "The normalized synthetic FHIR summary includes the following "
            "allergy history:\n" + "\n".join(allergy_lines)
        )
        excerpt = "; ".join(allergy.display for allergy in patient.allergies[:3])
    else:
        answer = (
            "The normalized synthetic FHIR summary does not include recorded "
            "allergy history for this patient."
        )
        excerpt = "No AllergyIntolerance records were included in the summary."
    return GeneratedResponse(
        answer=answer,
        citations=[
            _patient_summary_citation(category="allergies", excerpt=excerpt),
        ],
        disclaimer=EDUCATIONAL_DISCLAIMER,
    )


async def _finalize_patient_summary_response(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    patient = workflow.patient_data
    if patient is None:
        raise AssertionError("patient summary response requires patient data")
    response = _allergy_history_response(patient)
    completed_workflow, transition = transition_workflow(
        workflow,
        WorkflowStatus.COMPLETED,
        occurred_at=runtime.context.clock.now(),
        step=FINALIZE_PATIENT_SUMMARY_NODE,
        final_response=response,
    )
    audited_workflow = append_workflow_audit_events(
        completed_workflow,
        [
            _status_audit_event(
                completed_workflow,
                runtime,
                from_status=workflow.status,
                step=FINALIZE_PATIENT_SUMMARY_NODE,
            ),
        ],
    )
    return {"workflow": audited_workflow, "transitions": [transition]}


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


def _response_failure_code(error: ResponseGenerationError) -> str:
    if isinstance(error, ResponseGenerationTimeoutError):
        return RESPONSE_TIMEOUT_CODE
    if isinstance(error, ResponseGenerationAuthenticationError):
        return RESPONSE_AUTHENTICATION_CODE
    if isinstance(error, ResponseGenerationRateLimitError):
        return RESPONSE_RATE_LIMIT_CODE
    if isinstance(error, ResponseGenerationUnavailableError):
        return RESPONSE_UNAVAILABLE_CODE
    if isinstance(error, ResponseGenerationContextLimitError):
        return RESPONSE_CONTEXT_LIMIT_CODE
    if isinstance(error, ResponseGenerationRefusalError):
        return RESPONSE_REFUSAL_CODE
    if isinstance(error, ResponseGenerationInputError):
        return RESPONSE_INVALID_INPUT_CODE
    if isinstance(error, ResponseGenerationMalformedOutputError):
        return RESPONSE_INVALID_OUTPUT_CODE
    return RESPONSE_FAILURE_CODE


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
        request = build_grounded_generation_request(
            query=workflow.user_query,
            patient=patient,
            guidelines=workflow.retrieved_guidelines,
        )
        raw_result = await _run_bounded(
            lambda: runtime.context.response_generator.generate(
                request=request,
            ),
            runtime,
            retryable=(
                ResponseGenerationRateLimitError,
                ResponseGenerationUnavailableError,
            ),
            policy=runtime.context.response_execution_policy,
        )
        raw_payload = (
            raw_result.model_dump()
            if isinstance(raw_result, ResponseGenerationResult)
            else raw_result
        )
        generation = ResponseGenerationResult.model_validate(raw_payload)
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=RESPONSE_TIMEOUT_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except ResponseGenerationError as error:
        failure_code = _response_failure_code(error)
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=failure_code,
            failure_reason=error.reason_code,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except ValidationError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=GENERATE_RESPONSE_NODE,
            failure_code=RESPONSE_INVALID_OUTPUT_CODE,
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

    draft_workflow = set_workflow_response_draft(workflow, generation.draft)
    generation_details: dict[str, AuditValue] = {
        "generator": generation.metadata.generator,
        "outcome": "success",
        "citation_count": len(workflow.retrieved_guidelines),
    }
    for key, value in (
        ("model_alias", generation.metadata.model_alias),
        ("latency_ms", generation.metadata.latency_ms),
        ("input_tokens", generation.metadata.input_tokens),
        ("output_tokens", generation.metadata.output_tokens),
    ):
        if value is not None:
            generation_details[key] = value
    audited_workflow = append_workflow_audit_events(
        draft_workflow,
        [
            _audit_event(
                draft_workflow,
                runtime,
                AuditEventType.RESPONSE_GENERATED,
                details=generation_details,
            ),
        ],
    )
    return {"workflow": audited_workflow}


async def _post_generation_safety(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    if workflow.response_draft is None:
        raise AssertionError("post-generation safety requires a response draft")
    response_draft = workflow.response_draft
    try:
        raw_result = await _run_bounded(
            lambda: runtime.context.post_generation_safety_policy.evaluate_draft(
                query=workflow.user_query,
                draft=response_draft,
                citations=workflow.retrieved_guidelines,
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
        updated_workflow = set_workflow_post_generation_safety_result(
            workflow,
            safety_result,
        )
    except WorkflowNodeTimeoutError:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=POST_GENERATION_SAFETY_NODE,
            failure_code=POST_GENERATION_SAFETY_TIMEOUT_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except (SafetyPolicyError, ValidationError):
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=POST_GENERATION_SAFETY_NODE,
            failure_code=POST_GENERATION_SAFETY_FAILURE_CODE,
        )
        return {"workflow": failed_workflow, "transitions": [transition]}
    except Exception:
        failed_workflow, transition = _transition_with_audit(
            workflow,
            runtime,
            WorkflowStatus.FAILED,
            step=POST_GENERATION_SAFETY_NODE,
            failure_code=POST_GENERATION_SAFETY_FAILURE_CODE,
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
                    "phase": "post_generation",
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
            step=POST_GENERATION_SAFETY_NODE,
        )
        return {"workflow": reviewed_workflow, "transitions": [transition]}
    if safety_result.decision == SafetyDecision.BLOCK:
        blocked_workflow, transition = _transition_with_audit(
            audited_workflow,
            runtime,
            WorkflowStatus.REJECTED,
            step=POST_GENERATION_SAFETY_NODE,
        )
        return {"workflow": blocked_workflow, "transitions": [transition]}
    return {"workflow": audited_workflow}


async def _finalize_response(
    state: WorkflowGraphState,
    runtime: Runtime[WorkflowRuntime],
) -> WorkflowGraphUpdate:
    workflow = state["workflow"]
    if workflow.response_draft is None:
        raise AssertionError("final response requires a response draft")
    response = GeneratedResponse(
        answer=workflow.response_draft.answer,
        citations=workflow.retrieved_guidelines,
        disclaimer=EDUCATIONAL_DISCLAIMER,
    )
    completed_workflow, transition = transition_workflow(
        workflow,
        WorkflowStatus.COMPLETED,
        occurred_at=runtime.context.clock.now(),
        step=FINALIZE_RESPONSE_NODE,
        final_response=response,
    )
    audited_workflow = append_workflow_audit_events(
        completed_workflow,
        [
            _status_audit_event(
                completed_workflow,
                runtime,
                from_status=workflow.status,
                step=FINALIZE_RESPONSE_NODE,
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
    workflow = state["workflow"]
    if workflow.status == WorkflowStatus.FAILED:
        return "failed"
    if _is_allergy_history_query(workflow.user_query):
        return "patient_summary"
    return "guidelines"


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
    if _is_allergy_history_query(workflow.user_query):
        return "patient_summary"
    return "pass"


async def _route_generation(state: WorkflowGraphState) -> GenerationRoute:
    return (
        "failed" if state["workflow"].status == WorkflowStatus.FAILED else "generated"
    )


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
    builder.add_node(FINALIZE_PATIENT_SUMMARY_NODE, _finalize_patient_summary_response)
    builder.add_node(GENERATE_RESPONSE_NODE, _generate_response)
    builder.add_node(POST_GENERATION_SAFETY_NODE, _post_generation_safety)
    builder.add_node(FINALIZE_RESPONSE_NODE, _finalize_response)
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
            "patient_summary": SAFETY_PRECHECK_NODE,
            "guidelines": RETRIEVE_GUIDELINES_NODE,
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
            "patient_summary": FINALIZE_PATIENT_SUMMARY_NODE,
            "pass": GENERATE_RESPONSE_NODE,
            "review": END,
            "block": END,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        GENERATE_RESPONSE_NODE,
        _route_generation,
        {
            "generated": POST_GENERATION_SAFETY_NODE,
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        POST_GENERATION_SAFETY_NODE,
        _route_safety,
        {
            "patient_summary": FINALIZE_RESPONSE_NODE,
            "pass": FINALIZE_RESPONSE_NODE,
            "review": END,
            "block": END,
            "failed": END,
        },
    )
    builder.add_edge(REJECT_UNSUPPORTED_NODE, END)
    builder.add_edge(FINALIZE_PATIENT_SUMMARY_NODE, END)
    builder.add_edge(FINALIZE_RESPONSE_NODE, END)
    return builder.compile()


WORKFLOW_GRAPH = build_workflow_graph()


async def execute_workflow(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> WorkflowExecutionResult:
    """Execute the workflow and validate its provider-neutral result."""

    final_result: WorkflowExecutionResult | None = None
    async for event in stream_workflow(workflow, runtime=runtime):
        if event.result is not None:
            final_result = event.result
    if final_result is None:
        raise RuntimeError("workflow execution produced no node updates")
    return final_result


async def stream_workflow(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> AsyncIterator[WorkflowGraphEvent]:
    """Yield safe start and completion events for every LangGraph node."""

    transitions: list[WorkflowTransition] = []
    with ls.tracing_context(enabled=runtime.langsmith_tracing_enabled):
        async for stream_part in WORKFLOW_GRAPH.astream(
            {"workflow": workflow, "transitions": []},
            context=runtime,
            stream_mode=("tasks", "updates"),
            version="v2",
        ):
            if not isinstance(stream_part, dict):
                raise RuntimeError("workflow emitted an invalid stream event")
            stream_type = stream_part.get("type")
            stream_data = stream_part.get("data")
            if stream_type == "tasks":
                if isinstance(stream_data, dict) and "input" in stream_data:
                    node = stream_data.get("name")
                    if not isinstance(node, str):
                        raise RuntimeError("workflow emitted an invalid task event")
                    yield WorkflowGraphEvent(node=node, phase="started")
                continue
            if stream_type != "updates":
                continue
            raw_update = stream_data
            if not isinstance(raw_update, dict) or len(raw_update) != 1:
                raise RuntimeError("workflow emitted an invalid node update")
            node, update = next(iter(raw_update.items()))
            if not isinstance(node, str) or not isinstance(update, dict):
                raise RuntimeError("workflow emitted an invalid node update")
            node_transitions = update.get("transitions", [])
            if not isinstance(node_transitions, list):
                raise RuntimeError("workflow emitted invalid transitions")
            transitions.extend(
                WorkflowTransition.model_validate(transition)
                for transition in node_transitions
            )
            yield WorkflowGraphEvent(
                node=node,
                phase="completed",
                result=WorkflowExecutionResult.model_validate(
                    {
                        "workflow": update.get("workflow"),
                        "transitions": transitions,
                    }
                ),
            )


async def execute_workflow_skeleton(
    workflow: WorkflowState,
    *,
    runtime: WorkflowRuntime,
) -> WorkflowExecutionResult:
    """Backward-compatible name retained for callers from sub-phase 2.1."""

    return await execute_workflow(workflow, runtime=runtime)
