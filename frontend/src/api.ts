import { config } from "./config";

export type WorkflowStatus =
  | "queued"
  | "running"
  | "pending_review"
  | "completed"
  | "rejected"
  | "failed";

export interface ApiSuccess<T> {
  readonly request_id: string;
  readonly data: T;
}

export interface WorkflowStreamUpdate {
  readonly request_id: string;
  readonly node: string | null;
  readonly phase: "queued" | "started" | "completed";
  readonly data: WorkflowRunSnapshot;
}

export interface ApiErrorEnvelope {
  readonly request_id: string;
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly field?: string | null;
  };
}

export interface Citation {
  readonly document_id: string;
  readonly chunk_id: string;
  readonly title: string;
  readonly publisher: string;
  readonly source_url: string;
  readonly page?: number | null;
  readonly excerpt?: string | null;
}

export interface GuidelineEvidence {
  readonly assessment: "sufficient" | "insufficient" | "conflicting";
  readonly policy_version: string;
  readonly query_fingerprint: string;
  readonly match_count: number;
  readonly document_ids: readonly string[];
  readonly chunk_ids: readonly string[];
}

export interface SafetyReason {
  readonly code: string;
  readonly message: string;
  readonly severity: "info" | "warning" | "high";
  readonly evidence_references: readonly string[];
}

export interface SafetyResult {
  readonly decision: "pass" | "review" | "block";
  readonly requires_human_review: boolean;
  readonly policy_version: string;
  readonly reasons: readonly SafetyReason[];
}

export interface ResponseDraft {
  readonly answer: string;
}

export interface GeneratedResponse {
  readonly answer: string;
  readonly citations: readonly Citation[];
  readonly disclaimer: string;
}

export interface WorkflowTransition {
  readonly from_status: WorkflowStatus;
  readonly to_status: WorkflowStatus;
  readonly occurred_at: string;
  readonly step: string;
}

export interface AuditEvent {
  readonly event_id: string;
  readonly event_type: string;
  readonly occurred_at: string;
  readonly actor_type: string;
  readonly actor_id?: string | null;
  readonly details: Record<string, string | number | boolean | null>;
}

export interface WorkflowRunSnapshot {
  readonly workflow_id: string;
  readonly correlation_id: string;
  readonly trace_id: string;
  readonly status: WorkflowStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly requires_human_review?: boolean | null;
  readonly guideline_evidence?: GuidelineEvidence | null;
  readonly response_draft?: ResponseDraft | null;
  readonly review_citations: readonly Citation[];
  readonly safety_result?: SafetyResult | null;
  readonly post_generation_safety_result?: SafetyResult | null;
  readonly final_response?: GeneratedResponse | null;
  readonly failure_code?: string | null;
  readonly review_version: number;
  readonly transitions: readonly WorkflowTransition[];
  readonly audit_log: readonly AuditEvent[];
}

export interface ReviewQueueItem {
  readonly workflow_id: string;
  readonly correlation_id: string;
  readonly trace_id: string;
  readonly status: WorkflowStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly review_version: number;
  readonly requires_human_review: boolean;
  readonly guideline_evidence?: GuidelineEvidence | null;
  readonly response_draft?: ResponseDraft | null;
  readonly citations: readonly Citation[];
  readonly safety_result?: SafetyResult | null;
  readonly post_generation_safety_result?: SafetyResult | null;
}

export interface ReviewActionInput {
  readonly action: "approve" | "reject" | "request_changes";
  readonly reviewer_id: string;
  readonly rationale: string;
  readonly review_version: number;
}

export class ApiClientError extends Error {
  readonly code: string;
  readonly field?: string | null;
  readonly status: number;

  constructor(
    message: string,
    options: {
      readonly code: string;
      readonly status: number;
      readonly field?: string | null;
    },
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.status = options.status;
    this.field = options.field;
  }
}

function isApiError(value: unknown): value is ApiErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorEnvelope).error?.code === "string"
  );
}

function isWorkflowStreamUpdate(value: unknown): value is WorkflowStreamUpdate {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<WorkflowStreamUpdate>;
  return (
    typeof candidate.request_id === "string" &&
    (candidate.node === null || typeof candidate.node === "string") &&
    (candidate.phase === "queued" ||
      candidate.phase === "started" ||
      candidate.phase === "completed") &&
    typeof candidate.data === "object" &&
    candidate.data !== null &&
    typeof candidate.data.workflow_id === "string"
  );
}

function responseError(response: Response, payload: unknown): ApiClientError {
  if (isApiError(payload)) {
    return new ApiClientError(payload.error.message, {
      code: payload.error.code,
      status: response.status,
      field: payload.error.field,
    });
  }
  return new ApiClientError("Request failed.", {
    code: "request_failed",
    status: response.status,
  });
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiClientError("Backend is unavailable.", {
      code: "backend_unavailable",
      status: 0,
    });
  }

  const payload = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    throw responseError(response, payload);
  }

  return payload as T;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${config.apiBaseUrl}/health/live`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function createWorkflowRun(
  input: {
    readonly patientId: string;
    readonly query: string;
  },
  onUpdate?: (update: WorkflowStreamUpdate) => void,
): Promise<WorkflowRunSnapshot> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}/api/v1/workflows`, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        patient_id: input.patientId,
        query: input.query,
      }),
    });
  } catch {
    throw new ApiClientError("Backend is unavailable.", {
      code: "backend_unavailable",
      status: 0,
    });
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as unknown;
    throw responseError(response, payload);
  }
  if (!response.headers.get("content-type")?.includes("text/event-stream")) {
    const payload = (await response.json()) as ApiSuccess<WorkflowRunSnapshot>;
    onUpdate?.({
      request_id: payload.request_id,
      node: payload.data.transitions.at(-1)?.step ?? null,
      phase: "completed",
      data: payload.data,
    });
    return payload.data;
  }
  if (!response.body) {
    throw new ApiClientError("Workflow stream was unavailable.", {
      code: "workflow_stream_unavailable",
      status: response.status,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalSnapshot: WorkflowRunSnapshot | null = null;

  function consumeBlock(block: string): void {
    const lines = block.split("\n");
    const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
    const data = lines
      .filter((line) => line.startsWith("data: "))
      .map((line) => line.slice(6))
      .join("\n");
    if (!event || !data) {
      return;
    }
    const payload = JSON.parse(data) as unknown;
    if (event === "error") {
      throw responseError(response, payload);
    }
    if (event === "workflow" && isWorkflowStreamUpdate(payload)) {
      finalSnapshot = payload.data;
      onUpdate?.(payload);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      consumeBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim()) {
    consumeBlock(buffer.trim());
  }
  if (finalSnapshot === null) {
    throw new ApiClientError("Workflow stream ended without a result.", {
      code: "workflow_stream_incomplete",
      status: response.status,
    });
  }
  return finalSnapshot;
}

export async function getWorkflowRun(
  workflowId: string,
): Promise<WorkflowRunSnapshot> {
  const payload = await requestJson<ApiSuccess<WorkflowRunSnapshot>>(
    `/api/v1/workflows/${workflowId}`,
  );
  return payload.data;
}

export async function listReviews(): Promise<readonly ReviewQueueItem[]> {
  const payload = await requestJson<ApiSuccess<readonly ReviewQueueItem[]>>(
    "/api/v1/workflows/reviews",
  );
  return payload.data;
}

export async function getReview(workflowId: string): Promise<ReviewQueueItem> {
  const payload = await requestJson<ApiSuccess<ReviewQueueItem>>(
    `/api/v1/workflows/${workflowId}/review`,
  );
  return payload.data;
}

export async function recordReviewAction(
  workflowId: string,
  input: ReviewActionInput,
): Promise<WorkflowRunSnapshot> {
  const payload = await requestJson<ApiSuccess<WorkflowRunSnapshot>>(
    `/api/v1/workflows/${workflowId}/review-actions`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
  return payload.data;
}
