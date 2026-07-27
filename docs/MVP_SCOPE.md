# MVP Scope

## Product Statement

The AI Clinical Workflow Engine is an educational demonstration of auditable AI
workflow orchestration over synthetic healthcare data. It combines patient
context from FHIR, evidence from a curated clinical-guideline corpus,
deterministic safety checks, and human review.

It is not a medical device and must not be used to diagnose, treat, prescribe,
or make decisions about real patients.

## Primary User Story

As a demonstration user, I can select a synthetic patient and ask a
patient-specific clinical question. The system retrieves the minimum necessary
FHIR context and relevant guideline passages, evaluates whether human review is
required, and returns a cited response with an inspectable audit trail.

The first vertical slice supports one intent: `clinical_qa`.

## Representative Interaction

The exact API contract will be finalized during Phase 0.3. This example defines
the expected behavior, not a frozen wire format.

### Request

```json
{
  "patient_id": "synthetic-patient-001",
  "query": "What general precautions in the available guidelines are relevant to this patient's recorded conditions?"
}
```

### Response

```json
{
  "workflow_id": "generated-workflow-id",
  "status": "completed",
  "intent": "clinical_qa",
  "answer": "A concise, qualified summary based on retrieved evidence.",
  "citations": [
    {
      "title": "Example guideline",
      "publisher": "Trusted publisher",
      "source_url": "https://example.invalid/guideline",
      "page": 1
    }
  ],
  "safety": {
    "requires_human_review": false,
    "reasons": []
  }
}
```

If evidence is missing, patient context is insufficient, or a safety rule is
triggered, the workflow must qualify, refuse, or pause the response instead of
inventing an answer.

## MVP Capabilities

- Run locally using synthetic patient data.
- Accept a clinical-QA request for a selected synthetic patient.
- Retrieve and normalize relevant patient context from HAPI FHIR.
- Retrieve relevant passages from a curated guideline corpus in Weaviate.
- Generate structured, cited, and explicitly qualified output.
- Apply deterministic safety checks around LLM-assisted processing.
- Pause and resume a workflow for human approval.
- Persist workflow status, checkpoints, decisions, and audit events.
- Display request progress, evidence, safety status, and review actions in a
  React interface.
- Trace and evaluate the important workflow paths.

## Non-Goals

The MVP will not:

- Use real patient data or protected health information.
- Diagnose conditions or recommend patient-specific treatment.
- Prescribe, discontinue, or adjust medication.
- Replace professional medical judgment.
- Make autonomous clinical decisions.
- Provide emergency triage or monitoring.
- Modify FHIR clinical records.
- Implement appointment scheduling or medication-management workflows.
- Integrate with production EHR systems.
- Implement SMART on FHIR, production identity, or production authorization.
- Claim regulatory compliance or production readiness.
- Support every FHIR resource, LLM provider, vector store, or guideline format.

## Success Criteria

The MVP is successful when a new contributor can run a documented synthetic
clinical-QA scenario and observe:

1. Validated input and explicit intent routing.
2. Read-only FHIR context retrieval.
3. Guideline retrieval with usable citations.
4. A deterministic safety decision.
5. Human review for a deliberately flagged example.
6. A qualified final response or safe refusal.
7. A complete, correlated audit history and workflow visualization.

Quality is evaluated using fixed synthetic cases. A visually convincing answer
alone is not evidence of correctness.

