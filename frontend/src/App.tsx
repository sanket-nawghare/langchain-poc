import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ApiClientError,
  SafetyReason,
  WorkflowRunSnapshot,
  checkHealth,
  createWorkflowRun,
} from "./api";

type ApiStatus = "checking" | "available" | "unavailable";
type SubmitStatus = "idle" | "submitting" | "succeeded" | "failed";

const defaultPatientId = "synthetic-patient-1";

function statusLabel(status: WorkflowRunSnapshot["status"]): string {
  return status.replace("_", " ");
}

function safetyReasons(workflow: WorkflowRunSnapshot): readonly SafetyReason[] {
  return [
    ...(workflow.safety_result?.reasons ?? []),
    ...(workflow.post_generation_safety_result?.reasons ?? []),
  ];
}

function WorkflowResult({
  workflow,
}: {
  readonly workflow: WorkflowRunSnapshot;
}) {
  const reasons = safetyReasons(workflow);
  const response = workflow.final_response;
  const citations = response?.citations ?? workflow.review_citations;

  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Workflow result</p>
          <h2 id="result-title">Run status</h2>
        </div>
        <span className={`badge badge--${workflow.status}`}>
          {statusLabel(workflow.status)}
        </span>
      </div>

      <dl className="meta-grid" aria-label="Workflow metadata">
        <div>
          <dt>Workflow</dt>
          <dd>{workflow.workflow_id}</dd>
        </div>
        <div>
          <dt>Trace</dt>
          <dd>{workflow.trace_id}</dd>
        </div>
        <div>
          <dt>Review version</dt>
          <dd>{workflow.review_version}</dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>{workflow.guideline_evidence?.assessment ?? "not available"}</dd>
        </div>
      </dl>

      {response ? (
        <article className="answer">
          <h3>Generated answer</h3>
          <p>{response.answer}</p>
          <p className="disclaimer">{response.disclaimer}</p>
        </article>
      ) : null}

      {workflow.status === "pending_review" && workflow.response_draft ? (
        <article className="answer answer--review">
          <h3>Draft awaiting review</h3>
          <p>{workflow.response_draft.answer}</p>
        </article>
      ) : null}

      {workflow.failure_code ? (
        <p className="notice notice--danger">
          Failure: {workflow.failure_code}
        </p>
      ) : null}

      {reasons.length > 0 ? (
        <section className="reason-list" aria-labelledby="safety-title">
          <h3 id="safety-title">Safety reasons</h3>
          <ul>
            {reasons.map((reason) => (
              <li key={`${reason.code}:${reason.severity}`}>
                <span className={`severity severity--${reason.severity}`}>
                  {reason.severity}
                </span>
                <span>{reason.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {citations.length > 0 ? (
        <section className="citation-list" aria-labelledby="citations-title">
          <h3 id="citations-title">Citations</h3>
          <ul>
            {citations.map((citation) => (
              <li key={citation.chunk_id}>
                <a href={citation.source_url} target="_blank" rel="noreferrer">
                  {citation.title}
                </a>
                <span>
                  {citation.publisher}
                  {citation.page ? `, page ${citation.page}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [patientId, setPatientId] = useState(defaultPatientId);
  const [query, setQuery] = useState("");
  const [submitStatus, setSubmitStatus] = useState<SubmitStatus>("idle");
  const [workflow, setWorkflow] = useState<WorkflowRunSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(
    () => patientId.trim().length > 0 && query.trim().length > 0,
    [patientId, query],
  );

  useEffect(() => {
    let active = true;

    async function checkApi() {
      const available = await checkHealth();
      if (active) {
        setApiStatus(available ? "available" : "unavailable");
      }
    }

    void checkApi();
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      setError("Enter a synthetic patient ID and clinical question.");
      return;
    }

    setSubmitStatus("submitting");
    setError(null);
    try {
      const result = await createWorkflowRun({
        patientId: patientId.trim(),
        query: query.trim(),
      });
      setWorkflow(result);
      setSubmitStatus("succeeded");
    } catch (caught) {
      const message =
        caught instanceof ApiClientError
          ? `${caught.message} (${caught.code})`
          : "Workflow request failed.";
      setError(message);
      setSubmitStatus("failed");
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Synthetic data only</p>
          <h1>AI Clinical Workflow Engine</h1>
          <p className="summary">
            Submit a synthetic clinical question, inspect workflow routing, and
            keep generated output tied to reviewed guideline evidence.
          </p>
        </div>
        <div className={`status status--${apiStatus}`} role="status">
          <span aria-hidden="true" className="status__indicator" />
          Backend: {apiStatus}
        </div>
      </header>

      <div className="workspace">
        <section
          className="panel request-panel"
          aria-labelledby="request-title"
        >
          <div className="panel__header">
            <div>
              <p className="eyebrow">Workflow request</p>
              <h2 id="request-title">Clinical QA</h2>
            </div>
          </div>

          <form className="request-form" onSubmit={handleSubmit}>
            <label>
              <span>Synthetic patient ID</span>
              <input
                value={patientId}
                onChange={(event) => setPatientId(event.target.value)}
                autoComplete="off"
              />
            </label>
            <label>
              <span>Clinical question</span>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={6}
                placeholder="What precautions relate to this patient's conditions?"
              />
            </label>
            {error ? (
              <p className="notice notice--danger" role="alert">
                {error}
              </p>
            ) : null}
            <button
              type="submit"
              disabled={!canSubmit || submitStatus === "submitting"}
            >
              {submitStatus === "submitting"
                ? "Running workflow"
                : "Run workflow"}
            </button>
          </form>
        </section>

        {workflow ? (
          <WorkflowResult workflow={workflow} />
        ) : (
          <section
            className="panel empty-panel"
            aria-label="Workflow result empty state"
          >
            <p className="eyebrow">No run selected</p>
            <h2>Ready for a synthetic workflow</h2>
            <p>
              Results will appear here with status, evidence, safety reasons,
              citations, and final response details.
            </p>
          </section>
        )}
      </div>
    </main>
  );
}
