import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  ApiClientError,
  AuditEvent,
  ReviewQueueItem,
  SafetyReason,
  WorkflowTransition,
  WorkflowRunSnapshot,
  checkHealth,
  createWorkflowRun,
  listReviews,
  recordReviewAction,
} from "./api";

type ApiStatus = "checking" | "available" | "unavailable";
type SubmitStatus = "idle" | "submitting" | "succeeded" | "failed";
type ReviewStatus = "idle" | "loading" | "acting" | "failed";
type ViewMode = "run" | "review" | "history";

const defaultPatientId = "synthetic-patient-1";
const sampleQuestion = "What precautions relate to this patient's conditions?";
const workflowSteps = [
  { id: "begin_execution", label: "Begin" },
  { id: "classify_intent", label: "Intent" },
  { id: "retrieve_patient", label: "Patient" },
  { id: "retrieve_guidelines", label: "Guidelines" },
  { id: "safety_precheck", label: "Pre-check" },
  { id: "generate_response", label: "Draft" },
  { id: "post_generation_safety", label: "Draft safety" },
  { id: "finalize_response", label: "Finalize" },
] as const;

function statusLabel(status: WorkflowRunSnapshot["status"]): string {
  return status.replace("_", " ");
}

function safetyReasons(workflow: WorkflowRunSnapshot): readonly SafetyReason[] {
  return [
    ...(workflow.safety_result?.reasons ?? []),
    ...(workflow.post_generation_safety_result?.reasons ?? []),
  ];
}

function statusMessage(workflow: WorkflowRunSnapshot): string {
  if (workflow.status === "completed") {
    return "Completed with grounded citations and recorded safety checks.";
  }
  if (workflow.status === "pending_review") {
    return "Paused for reviewer action before the draft can be published.";
  }
  if (workflow.status === "rejected") {
    return "Stopped without publishing a final response.";
  }
  if (workflow.status === "failed") {
    return "Stopped because one workflow dependency or contract failed safely.";
  }
  return "Workflow is still being processed.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function WorkflowTimeline({
  transitions,
}: {
  readonly transitions: readonly WorkflowTransition[];
}) {
  if (transitions.length === 0) {
    return (
      <p className="notice">No transitions have been recorded for this run.</p>
    );
  }
  return (
    <ol className="timeline" aria-label="Workflow transitions">
      {transitions.map((transition, index) => (
        <li key={`${transition.step}:${transition.occurred_at}:${index}`}>
          <span>{transition.step.replaceAll("_", " ")}</span>
          <small>
            {transition.from_status} to {transition.to_status}
          </small>
        </li>
      ))}
    </ol>
  );
}

function AuditSummary({
  auditLog,
}: {
  readonly auditLog: readonly AuditEvent[];
}) {
  if (auditLog.length === 0) {
    return <p className="notice">No audit events are available yet.</p>;
  }
  return (
    <ul className="audit-list" aria-label="Redacted audit events">
      {auditLog.slice(-6).map((event) => (
        <li key={event.event_id}>
          <span>{event.event_type.replaceAll("_", " ")}</span>
          <small>{event.actor_type}</small>
        </li>
      ))}
    </ul>
  );
}

function WorkflowGraph({
  workflow,
}: {
  readonly workflow: WorkflowRunSnapshot | null;
}) {
  const transitionSteps = new Set(
    workflow?.transitions.map((transition) => transition.step) ?? [],
  );
  const activeStep = workflow?.transitions.at(-1)?.step;
  const nodes: Node[] = workflowSteps.map((step, index) => {
    const completed = transitionSteps.has(step.id);
    const active = activeStep === step.id;
    return {
      id: step.id,
      position: { x: (index % 4) * 190, y: Math.floor(index / 4) * 120 },
      data: { label: step.label },
      className: active
        ? "workflow-node workflow-node--active"
        : completed
          ? "workflow-node workflow-node--complete"
          : "workflow-node",
      draggable: false,
    };
  });
  const edges: Edge[] = workflowSteps.slice(1).map((step, index) => ({
    id: `${workflowSteps[index].id}-${step.id}`,
    source: workflowSteps[index].id,
    target: step.id,
    animated: activeStep === step.id,
  }));

  return (
    <section className="panel graph-panel" aria-labelledby="graph-title">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Workflow graph</p>
          <h2 id="graph-title">Execution path</h2>
        </div>
        {workflow ? (
          <span className={`badge badge--${workflow.status}`}>
            {statusLabel(workflow.status)}
          </span>
        ) : null}
      </div>
      <div className="flow-frame" role="img" aria-label="Workflow graph nodes">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </section>
  );
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
      <p className="result-summary">{statusMessage(workflow)}</p>

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
        <div>
          <dt>Updated</dt>
          <dd>{formatDate(workflow.updated_at)}</dd>
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

      <section className="detail-grid" aria-label="Workflow details">
        <div>
          <h3>Transitions</h3>
          <WorkflowTimeline transitions={workflow.transitions} />
        </div>
        <div>
          <h3>Audit</h3>
          <AuditSummary auditLog={workflow.audit_log} />
        </div>
      </section>
    </section>
  );
}

function RunHistory({
  runs,
  selectedId,
  onSelect,
}: {
  readonly runs: readonly WorkflowRunSnapshot[];
  readonly selectedId?: string;
  readonly onSelect: (workflow: WorkflowRunSnapshot) => void;
}) {
  return (
    <section className="panel history-panel" aria-labelledby="history-title">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Local history</p>
          <h2 id="history-title">Recent runs</h2>
        </div>
      </div>
      {runs.length === 0 ? (
        <p className="notice">Submitted workflows will appear here.</p>
      ) : (
        <ul className="run-list">
          {runs.map((run) => (
            <li key={run.workflow_id}>
              <button
                className="run-list__button"
                type="button"
                aria-current={run.workflow_id === selectedId}
                onClick={() => onSelect(run)}
              >
                <span>{statusLabel(run.status)}</span>
                <small>{formatDate(run.updated_at)}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function reviewReasons(review: ReviewQueueItem): readonly SafetyReason[] {
  return [
    ...(review.safety_result?.reasons ?? []),
    ...(review.post_generation_safety_result?.reasons ?? []),
  ];
}

function ReviewPanel({
  reviews,
  selectedReview,
  reviewStatus,
  reviewError,
  reviewerId,
  rationale,
  onLoad,
  onSelect,
  onReviewerId,
  onRationale,
  onAction,
}: {
  readonly reviews: readonly ReviewQueueItem[];
  readonly selectedReview: ReviewQueueItem | null;
  readonly reviewStatus: ReviewStatus;
  readonly reviewError: string | null;
  readonly reviewerId: string;
  readonly rationale: string;
  readonly onLoad: () => void;
  readonly onSelect: (review: ReviewQueueItem) => void;
  readonly onReviewerId: (value: string) => void;
  readonly onRationale: (value: string) => void;
  readonly onAction: (
    action: "approve" | "reject" | "request_changes",
  ) => Promise<void>;
}) {
  const reasons = selectedReview ? reviewReasons(selectedReview) : [];

  return (
    <section className="panel review-panel" aria-labelledby="review-title">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Human review</p>
          <h2 id="review-title">Pending queue</h2>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={onLoad}
          disabled={reviewStatus === "loading"}
        >
          {reviewStatus === "loading" ? "Refreshing" : "Refresh"}
        </button>
      </div>

      {reviewError ? (
        <p className="notice notice--danger" role="alert">
          {reviewError}
        </p>
      ) : null}

      <div className="review-layout">
        <div>
          {reviews.length === 0 ? (
            <p className="notice">No pending reviews are queued.</p>
          ) : (
            <ul className="run-list" aria-label="Pending reviews">
              {reviews.map((review) => (
                <li key={review.workflow_id}>
                  <button
                    className="run-list__button"
                    type="button"
                    aria-current={
                      review.workflow_id === selectedReview?.workflow_id
                    }
                    onClick={() => onSelect(review)}
                  >
                    <span>Version {review.review_version}</span>
                    <small>{formatDate(review.updated_at)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="review-detail">
          {selectedReview ? (
            <>
              <dl className="meta-grid meta-grid--compact">
                <div>
                  <dt>Workflow</dt>
                  <dd>{selectedReview.workflow_id}</dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>
                    {selectedReview.guideline_evidence?.assessment ??
                      "not available"}
                  </dd>
                </div>
                <div>
                  <dt>Review version</dt>
                  <dd>{selectedReview.review_version}</dd>
                </div>
              </dl>

              {selectedReview.response_draft ? (
                <article className="answer answer--review">
                  <h3>Draft awaiting review</h3>
                  <p>{selectedReview.response_draft.answer}</p>
                </article>
              ) : null}

              {reasons.length > 0 ? (
                <section className="reason-list">
                  <h3>Safety reasons</h3>
                  <ul>
                    {reasons.map((reason) => (
                      <li key={`${reason.code}:${reason.severity}`}>
                        <span
                          className={`severity severity--${reason.severity}`}
                        >
                          {reason.severity}
                        </span>
                        <span>{reason.message}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {selectedReview.citations.length > 0 ? (
                <section className="citation-list">
                  <h3>Citations</h3>
                  <ul>
                    {selectedReview.citations.map((citation) => (
                      <li key={citation.chunk_id}>
                        <a
                          href={citation.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
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

              <form className="request-form review-form">
                <label>
                  <span>Reviewer ID</span>
                  <input
                    value={reviewerId}
                    onChange={(event) => onReviewerId(event.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label>
                  <span>Rationale</span>
                  <textarea
                    value={rationale}
                    onChange={(event) => onRationale(event.target.value)}
                    rows={4}
                  />
                </label>
                <div className="action-row">
                  <button
                    type="button"
                    disabled={reviewStatus === "acting"}
                    onClick={() => void onAction("approve")}
                  >
                    Approve
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={reviewStatus === "acting"}
                    onClick={() => void onAction("reject")}
                  >
                    Reject
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={reviewStatus === "acting"}
                    onClick={() => void onAction("request_changes")}
                  >
                    Request changes
                  </button>
                </div>
              </form>
            </>
          ) : (
            <p className="notice">Select a pending review to inspect it.</p>
          )}
        </div>
      </div>
    </section>
  );
}

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [patientId, setPatientId] = useState(defaultPatientId);
  const [query, setQuery] = useState("");
  const [submitStatus, setSubmitStatus] = useState<SubmitStatus>("idle");
  const [workflow, setWorkflow] = useState<WorkflowRunSnapshot | null>(null);
  const [runHistory, setRunHistory] = useState<WorkflowRunSnapshot[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("run");
  const [error, setError] = useState<string | null>(null);
  const [reviews, setReviews] = useState<ReviewQueueItem[]>([]);
  const [selectedReview, setSelectedReview] = useState<ReviewQueueItem | null>(
    null,
  );
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>("idle");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewerId, setReviewerId] = useState("reviewer-1");
  const [rationale, setRationale] = useState("");

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
      setRunHistory((current) => [
        result,
        ...current.filter((run) => run.workflow_id !== result.workflow_id),
      ]);
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

  async function refreshReviews() {
    setReviewStatus("loading");
    setReviewError(null);
    try {
      const result = await listReviews();
      setReviews([...result]);
      setSelectedReview((current) => {
        if (!current) {
          return result[0] ?? null;
        }
        return (
          result.find((review) => review.workflow_id === current.workflow_id) ??
          result[0] ??
          null
        );
      });
      setReviewStatus("idle");
    } catch (caught) {
      const message =
        caught instanceof ApiClientError
          ? `${caught.message} (${caught.code})`
          : "Review queue could not be loaded.";
      setReviewError(message);
      setReviewStatus("failed");
    }
  }

  async function handleReviewAction(
    action: "approve" | "reject" | "request_changes",
  ) {
    if (!selectedReview) {
      setReviewError("Select a pending review first.");
      return;
    }
    if (!reviewerId.trim() || !rationale.trim()) {
      setReviewError("Enter reviewer ID and rationale.");
      return;
    }

    setReviewStatus("acting");
    setReviewError(null);
    try {
      const result = await recordReviewAction(selectedReview.workflow_id, {
        action,
        reviewer_id: reviewerId.trim(),
        rationale: rationale.trim(),
        review_version: selectedReview.review_version,
      });
      setWorkflow(result);
      setRunHistory((current) => [
        result,
        ...current.filter((run) => run.workflow_id !== result.workflow_id),
      ]);
      const remaining = reviews.filter(
        (review) => review.workflow_id !== selectedReview.workflow_id,
      );
      setReviews(remaining);
      setSelectedReview(remaining[0] ?? null);
      setRationale("");
      setViewMode("run");
      setReviewStatus("idle");
    } catch (caught) {
      const message =
        caught instanceof ApiClientError
          ? `${caught.message} (${caught.code})`
          : "Review action could not be applied.";
      setReviewError(message);
      setReviewStatus("failed");
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

      <nav className="tabs" aria-label="Phase 5 workspace">
        <button
          type="button"
          aria-pressed={viewMode === "run"}
          onClick={() => setViewMode("run")}
        >
          Request
        </button>
        <button
          type="button"
          aria-pressed={viewMode === "review"}
          onClick={() => setViewMode("review")}
        >
          Review
        </button>
        <button
          type="button"
          aria-pressed={viewMode === "history"}
          onClick={() => setViewMode("history")}
        >
          History
        </button>
      </nav>

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
                placeholder={sampleQuestion}
              />
            </label>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setQuery(sampleQuestion)}
            >
              Use sample question
            </button>
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

      <div className="workspace workspace--single">
        <WorkflowGraph workflow={workflow} />
      </div>

      {viewMode === "review" ? (
        <div className="workspace workspace--single">
          <ReviewPanel
            reviews={reviews}
            selectedReview={selectedReview}
            reviewStatus={reviewStatus}
            reviewError={reviewError}
            reviewerId={reviewerId}
            rationale={rationale}
            onLoad={() => void refreshReviews()}
            onSelect={setSelectedReview}
            onReviewerId={setReviewerId}
            onRationale={setRationale}
            onAction={handleReviewAction}
          />
        </div>
      ) : null}

      {viewMode === "history" ? (
        <div className="workspace workspace--single">
          <RunHistory
            runs={runHistory}
            selectedId={workflow?.workflow_id}
            onSelect={setWorkflow}
          />
        </div>
      ) : null}
    </main>
  );
}
