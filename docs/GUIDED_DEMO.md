# Guided MVP Demo

This walkthrough proves the current MVP with synthetic data only.

## Start

Fast path from a clean checkout:

```bash
make demo-up
```

If you prefer separate terminals:

```bash
make setup
make infra-up
make fhir-seed
make guidelines-fetch
make guidelines-index
make backend-dev
make frontend-dev
```

Open `http://localhost:5173`.

## Seeded Patients

| Alias | Patient ID | Best demo use |
|---|---|---|
| `allergy-respiratory-01` | `3fb40e1f-64bc-665b-cde0-95a603de7747` | Allergy summary |
| `metabolic-01` | `19e902a8-bfaf-b0de-9892-cb0388cbfd5f` | Type 2 diabetes guideline questions |
| `cardiovascular-01` | `2cdc06fd-f758-01e7-7aa5-4a47108357d3` | Hypertension guideline questions |
| `sparse-control-01` | `0782a4ac-be89-df96-7de4-0ace0a54d346` | Missing/limited context behavior |

## Demo 1 - Direct Patient Evidence

Patient ID:

```text
3fb40e1f-64bc-665b-cde0-95a603de7747
```

Question:

```text
What are the current allergies for this patient?
```

Expected result:

- status: `completed`;
- graph ends through the patient-facts/direct-summary path;
- no LLM call is required;
- final answer cites the local synthetic patient summary evidence page.

## Demo 2 - Hypertension Guideline RAG

Patient ID:

```text
2cdc06fd-f758-01e7-7aa5-4a47108357d3
```

Question:

```text
What blood pressure target is recommended for adults?
```

Expected result:

- status: `completed` when the configured response provider returns a valid
  draft;
- citations from the WHO hypertension guideline;
- generated answer plus educational disclaimer;
- graph visibly passes through guidelines, pre-check, draft, draft safety, and
  finalize.

## Demo 3 - Type 2 Diabetes Guideline RAG

Patient ID:

```text
19e902a8-bfaf-b0de-9892-cb0388cbfd5f
```

Question:

```text
How should glycaemic control be monitored in type 2 diabetes?
```

Expected result:

- status: `completed` when the configured response provider returns a valid
  draft;
- citations from the WHO HEARTS-D diabetes document;
- generated answer plus educational disclaimer.

## Demo 4 - Safety Review

Patient ID:

```text
2cdc06fd-f758-01e7-7aa5-4a47108357d3
```

Question:

```text
Should this patient start hypertension medication?
```

Expected result:

- status: `pending_review`;
- safety reason explains that medication-change language requires review;
- review queue contains the item;
- Approve is disabled if the pause happened before generation because there is
  no draft to publish;
- Reject and Request changes are available reviewer actions.

## Capture Points

Use these for screenshots or a short demo recording:

1. Request tab before running Demo 2.
2. Execution graph while the Draft node is active.
3. Completed result with citations and disclaimer visible.
4. Review tab showing a pre-generation medication-change review.
5. History tab showing the completed and pending runs.
6. `/health/metrics` showing local request and failure counters.

Do not capture API keys, `.env` files, raw FHIR bundles, downloaded guideline
PDFs, or real patient data.
