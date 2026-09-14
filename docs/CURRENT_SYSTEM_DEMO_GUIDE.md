# Current System Capabilities and Demo Guide

This document describes what the current implementation can demonstrate
reliably. It is intentionally narrower than the long-term product roadmap.

> This project uses synthetic data for educational demonstration only. It is
> not a medical device, does not provide medical advice, and must not be used
> with real patient data.

## What the System Is Useful For

The current system is best presented as an **auditable clinical-AI workflow
prototype**, not as a general clinical expert. It demonstrates how an
application can:

- read and normalize a synthetic patient summary from local HAPI FHIR;
- retrieve reviewed WHO guideline passages from local Weaviate;
- generate a bounded answer from patient context and retrieved evidence;
- attach source citations and an educational disclaimer;
- apply deterministic checks before and after generation;
- pause unsafe or uncertain runs for human review;
- persist workflow state, transitions, review actions, and audit events; and
- visualize the LangGraph execution path in the React interface.

## Current Knowledge Boundary

### Direct patient-data answers

The production workflow currently has one direct FHIR-summary response:

- recorded allergy history, including normalized status and effective date.

These questions use local FHIR data and do not require Weaviate or an LLM:

- `What are the current allergies for this patient?`
- `What is the allergy history of this patient?`
- `List the known allergies for this patient.`
- `Does this patient have any recorded allergies?`

Use a seeded synthetic patient known to contain `AllergyIntolerance` records.
The response should complete with a citation to the local synthetic-patient
summary evidence page.

HAPI FHIR also contains and the backend normalizes conditions, medications,
observations, diagnostic reports, procedures, and encounters. However, the
workflow does **not yet have direct response routes** for those categories.
Their presence in HAPI therefore does not mean a standalone question about
them can currently be answered.

### Guideline-backed answers

The current reviewed Weaviate corpus contains two WHO documents:

1. *Guideline for the pharmacological treatment of hypertension in adults*
   (2021).
2. *Diagnosis and management of type 2 diabetes (HEARTS-D)* (2020).

The following four questions are the strongest demo questions because they
are part of the committed retrieval evaluation suite:

- `What blood pressure target is recommended for adults?`
- `When should pharmacological treatment for hypertension be initiated?`
- `What diagnostic criteria are used for type 2 diabetes?`
- `How should glycaemic control be monitored in type 2 diabetes?`

For these questions, the expected successful path is:

```text
Validate request
  -> classify clinical QA
  -> retrieve synthetic patient summary
  -> retrieve WHO guideline passages from Weaviate
  -> run deterministic safety pre-check
  -> generate a grounded draft
  -> run post-generation safety checks
  -> return a cited final response
```

This path requires HAPI FHIR, Weaviate, the backend, and the configured
response generator to be available. A real provider produces the meaningful
generated answer; the `fake` provider is useful for deterministic workflow and
UI demonstrations without provider rate limits.

## Recommended Demo Sequence

### 1. Demonstrate local patient evidence

Select a synthetic patient with known allergies and ask:

```text
What are the current allergies for this patient?
```

Show the normalized allergy answer, local citation, execution graph,
transitions, and audit events. Explain that this route is deterministic and
does not call the LLM.

### 2. Demonstrate RAG and grounded generation

Ask:

```text
What blood pressure target is recommended for adults?
```

Show the WHO citations, page metadata, retrieved excerpts, generated answer,
disclaimer, execution graph, and audit trail.

If that wording does not retrieve sufficient evidence after the index has
been changed, run the committed evaluation gate before the demo rather than
trying unrelated questions.

### 3. Demonstrate the second knowledge area

Ask:

```text
How should glycaemic control be monitored in type 2 diabetes?
```

Show that the workflow retrieves the HEARTS-D document rather than the
hypertension guideline.

### 4. Demonstrate safety and human review

Ask:

```text
Should this patient start hypertension medication?
```

This wording is intended to demonstrate the conservative medication-change
rule. If relevant guideline evidence is retrieved, the safety pre-check should
pause the workflow before generation.

For a pre-generation review there is no draft to approve. The current review
UI therefore enables **Reject** and **Request changes**, while **Approve**
remains disabled. Approval currently means publishing an existing
post-generation draft; it does not mean authorizing a pre-generation workflow
to continue.

## Questions to Avoid in the Current Demo

The following categories are outside the implemented answer routes or indexed
knowledge boundary:

- `What are this patient's active conditions?`
- `List this patient's medications.`
- `What were this patient's latest lab results?`
- `What procedures has this patient had?`
- `Assess this patient's risk of hypertension.`
- `Diagnose this patient.`
- `Create a treatment plan for this patient.`
- `What medication or dose should this patient take?`
- questions about vaccinations, fractures, oncology, pediatrics, or other
  topics not covered by the two indexed WHO documents;
- scheduling, prescription, refill, or FHIR write requests.

Patient conditions and medications may exist in HAPI, but standalone requests
for them currently fall through to guideline retrieval. They normally produce
`insufficient` evidence and pause without creating a response draft.

## How to Interpret Demo Outcomes

| Outcome | Meaning |
|---|---|
| `completed` | A deterministic patient answer or a cited guideline-backed answer was finalized. |
| `pending_review` with a draft | Post-generation checks require a reviewer; approval may finalize the draft when citations exist. |
| `pending_review` without a draft | Evidence or a pre-generation safety rule stopped the run; there is nothing for Approve to publish. |
| `rejected` | The request was unsupported, blocked by policy, or ended through a reviewer action. |
| `failed` | A dependency or contract failed safely; inspect `failure_code`. |
| `response_generation_rate_limited` | FHIR and retrieval may have succeeded, but the configured LLM provider rejected the generation request due to its rate limit. |
| `response_generation_invalid_output` | The provider response did not satisfy the strict structured-output contract. |

## Pre-Demo Checklist

- HAPI FHIR is running and contains the selected synthetic cohort.
- Weaviate is running and the reviewed guideline corpus is indexed.
- Backend readiness reports that its required dependencies are available.
- The frontend points to the local backend.
- For a live-answer demo, the provider key, model, quota, and rate limit are
  valid.
- For a deterministic workflow demo, use `CLINICAL_LLM_PROVIDER=fake` and
  restart the backend after changing the environment.
- Run the retrieval live gate if the guideline index may have changed.

## Honest Demo Positioning

A concise description for an audience is:

> The system is a synthetic-data clinical workflow demonstration specialized
> in direct allergy-history summaries and cited answers from a small reviewed
> WHO corpus covering adult hypertension treatment and type 2 diabetes. Its
> main value is the observable orchestration around evidence retrieval,
> bounded generation, deterministic safety controls, human review, and audit
> history—not broad medical question answering.

