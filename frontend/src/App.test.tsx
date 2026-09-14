import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

type WorkflowOverride = {
  readonly status?: string;
  readonly final_response?: object | null;
  readonly response_draft?: object | null;
  readonly failure_code?: string | null;
  readonly post_generation_safety_result?: object | null;
};

function workflowPayload(
  status = 201,
  override: WorkflowOverride = {},
): Response {
  return new Response(
    JSON.stringify({
      request_id: "request-1",
      data: {
        workflow_id: "workflow-1",
        correlation_id: "correlation-1",
        trace_id: "trace-1",
        status: override.status ?? "completed",
        created_at: "2026-09-14T00:00:00Z",
        updated_at: "2026-09-14T00:00:01Z",
        requires_human_review: false,
        guideline_evidence: {
          assessment: "sufficient",
          policy_version: "retrieval-v1",
          query_fingerprint: "0".repeat(64),
          match_count: 1,
          document_ids: ["who-synthetic-guideline"],
          chunk_ids: ["who-synthetic-guideline.0"],
        },
        response_draft: override.response_draft ?? {
          answer: "Guideline evidence supports routine follow-up.",
        },
        review_citations: [
          {
            document_id: "who-synthetic-guideline",
            chunk_id: "who-synthetic-guideline.0",
            title: "Reviewed synthetic guideline",
            publisher: "who",
            source_url: "https://example.test/reviewed-guideline",
            page: 1,
            excerpt: "Bounded patient-summary or guideline excerpt.",
          },
        ],
        safety_result: {
          decision: "pass",
          requires_human_review: false,
          policy_version: "safety-precheck-v1",
          reasons: [],
        },
        post_generation_safety_result:
          override.post_generation_safety_result ?? {
            decision: "pass",
            requires_human_review: false,
            policy_version: "safety-post-generation-v1",
            reasons: [],
          },
        final_response: override.final_response ?? {
          answer: "Guideline evidence supports routine follow-up.",
          citations: [
            {
              document_id: "who-synthetic-guideline",
              chunk_id: "who-synthetic-guideline.0",
              title: "Reviewed synthetic guideline",
              publisher: "who",
              source_url: "https://example.test/reviewed-guideline",
              page: 1,
              excerpt: "Bounded patient-summary or guideline excerpt.",
            },
          ],
          disclaimer: "Educational demonstration; not medical advice.",
        },
        failure_code: override.failure_code ?? null,
        review_version: 0,
        transitions: [
          {
            from_status: "queued",
            to_status: "running",
            occurred_at: "2026-09-14T00:00:00Z",
            step: "begin_execution",
          },
          {
            from_status: "running",
            to_status: override.status ?? "completed",
            occurred_at: "2026-09-14T00:00:01Z",
            step:
              override.status === "pending_review"
                ? "post_generation_safety"
                : "finalize_response",
          },
        ],
        audit_log: [
          {
            event_id: "event-1",
            event_type: "response_generated",
            occurred_at: "2026-09-14T00:00:01Z",
            actor_type: "system",
            details: { outcome: "success" },
          },
        ],
      },
    }),
    { status },
  );
}

function reviewPayload(status = 200): Response {
  return new Response(
    JSON.stringify({
      request_id: "request-2",
      data: [
        {
          workflow_id: "workflow-review-1",
          correlation_id: "correlation-review-1",
          trace_id: "trace-review-1",
          status: "pending_review",
          created_at: "2026-09-14T00:00:00Z",
          updated_at: "2026-09-14T00:00:01Z",
          review_version: 0,
          requires_human_review: true,
          guideline_evidence: {
            assessment: "sufficient",
            policy_version: "retrieval-v1",
            query_fingerprint: "0".repeat(64),
            match_count: 1,
            document_ids: ["who-synthetic-guideline"],
            chunk_ids: ["who-synthetic-guideline.0"],
          },
          response_draft: {
            answer: "Start this medication dose based on guideline evidence.",
          },
          citations: [
            {
              document_id: "who-synthetic-guideline",
              chunk_id: "who-synthetic-guideline.0",
              title: "Reviewed synthetic guideline",
              publisher: "who",
              source_url: "https://example.test/reviewed-guideline",
              page: 1,
            },
          ],
          safety_result: {
            decision: "pass",
            requires_human_review: false,
            policy_version: "safety-precheck-v1",
            reasons: [],
          },
          post_generation_safety_result: {
            decision: "review",
            requires_human_review: true,
            policy_version: "safety-post-generation-v1",
            reasons: [
              {
                code: "draft_autonomous_medication_change",
                message:
                  "Generated draft includes medication-change language requiring review.",
                severity: "high",
                evidence_references: ["draft:answer"],
              },
            ],
          },
        },
      ],
    }),
    { status },
  );
}

function preGenerationReviewPayload(status = 200): Response {
  return new Response(
    JSON.stringify({
      request_id: "request-2",
      data: [
        {
          workflow_id: "workflow-review-1",
          correlation_id: "correlation-review-1",
          trace_id: "trace-review-1",
          status: "pending_review",
          created_at: "2026-09-14T00:00:00Z",
          updated_at: "2026-09-14T00:00:01Z",
          review_version: 0,
          requires_human_review: true,
          guideline_evidence: null,
          response_draft: null,
          citations: [],
          safety_result: {
            decision: "review",
            requires_human_review: true,
            policy_version: "safety-precheck-v1",
            reasons: [
              {
                code: "medication_or_allergy_risk_review",
                message: "The request needs review before response generation.",
                severity: "high",
                evidence_references: ["query:intent"],
              },
            ],
          },
          post_generation_safety_result: null,
        },
      ],
    }),
    { status },
  );
}

function reviewActionResponse(): Response {
  return workflowPayload(200, {
    status: "completed",
    final_response: {
      answer: "Start this medication dose based on guideline evidence.",
      citations: [
        {
          document_id: "who-synthetic-guideline",
          chunk_id: "who-synthetic-guideline.0",
          title: "Reviewed synthetic guideline",
          publisher: "who",
          source_url: "https://example.test/reviewed-guideline",
          page: 1,
        },
      ],
      disclaimer: "Educational demonstration; not medical advice.",
    },
  });
}

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the Phase 5 shell and reports an available backend", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "AI Clinical Workflow Engine" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Clinical QA" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Workflow graph nodes" }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Backend: available",
      );
    });
  });

  it("submits a workflow and renders the completed response safely", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(workflowPayload());

    render(<App />);

    fireEvent.change(screen.getByLabelText("Clinical question"), {
      target: { value: "What precautions relate to these conditions?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    await waitFor(() => {
      expect(
        screen.getByText("Guideline evidence supports routine follow-up."),
      ).toBeInTheDocument();
    });
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Reviewed synthetic guideline"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bounded patient-summary or guideline excerpt."),
    ).toBeInTheDocument();
    expect(screen.getByText("finalize response")).toBeInTheDocument();
    expect(screen.getByText("response generated")).toBeInTheDocument();
    expect(screen.getByText("Execution path")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("patient_data");
    expect(document.body).not.toHaveTextContent("private-code");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/v1/workflows",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("renders workflow progress before the SSE stream completes", async () => {
    const completedEnvelope = (await workflowPayload().json()) as {
      request_id: string;
      data: Record<string, unknown>;
    };
    const queuedData = {
      ...completedEnvelope.data,
      status: "queued",
      updated_at: "2026-09-14T00:00:00Z",
      guideline_evidence: null,
      response_draft: null,
      review_citations: [],
      safety_result: null,
      post_generation_safety_result: null,
      final_response: null,
      transitions: [],
      audit_log: [],
    };
    const runningData = {
      ...queuedData,
      status: "running",
      transitions: [
        {
          from_status: "queued",
          to_status: "running",
          occurred_at: "2026-09-14T00:00:00Z",
          step: "begin_execution",
        },
      ],
    };
    const encoder = new TextEncoder();
    let finishStream: (() => void) | undefined;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const event = (node: string | null, phase: string, data: object) =>
          `event: workflow\ndata: ${JSON.stringify({
            request_id: completedEnvelope.request_id,
            node,
            phase,
            data,
          })}\n\n`;
        controller.enqueue(encoder.encode(event(null, "queued", queuedData)));
        controller.enqueue(
          encoder.encode(event("begin_execution", "started", queuedData)),
        );
        controller.enqueue(
          encoder.encode(event("begin_execution", "completed", runningData)),
        );
        controller.enqueue(
          encoder.encode(event("classify_intent", "started", runningData)),
        );
        finishStream = () => {
          controller.enqueue(
            encoder.encode(
              event("finalize_response", "completed", completedEnvelope.data),
            ),
          );
          controller.close();
        };
      },
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );

    render(<App />);
    fireEvent.click(
      screen.getByRole("button", { name: "Use sample question" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    await waitFor(() => {
      expect(screen.getAllByText("running").length).toBeGreaterThan(0);
    });
    expect(
      screen.getByRole("button", { name: "Running workflow" }),
    ).toBeDisabled();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/v1/workflows",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Accept: "text/event-stream" }),
      }),
    );

    finishStream?.();
    await waitFor(() => {
      expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    });
  });

  it("renders pending-review draft and safety reasons", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        workflowPayload(201, {
          status: "pending_review",
          final_response: null,
          response_draft: {
            answer: "Start this medication dose based on guideline evidence.",
          },
          post_generation_safety_result: {
            decision: "review",
            requires_human_review: true,
            policy_version: "safety-post-generation-v1",
            reasons: [
              {
                code: "draft_autonomous_medication_change",
                message:
                  "Generated draft includes medication-change language requiring review.",
                severity: "high",
                evidence_references: ["draft:answer"],
              },
            ],
          },
        }),
      );

    render(<App />);

    fireEvent.click(
      screen.getByRole("button", { name: "Use sample question" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    await waitFor(() => {
      expect(screen.getAllByText("pending review").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Draft awaiting review")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Generated draft includes medication-change language requiring review.",
      ),
    ).toBeInTheDocument();
  });

  it("shows safe API errors", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            request_id: "request-1",
            error: {
              code: "invalid_workflow_request",
              message: "The workflow request is invalid.",
            },
          }),
          { status: 400 },
        ),
      );

    render(<App />);

    fireEvent.click(
      screen.getByRole("button", { name: "Use sample question" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "invalid_workflow_request",
      );
    });
    expect(document.body).not.toHaveTextContent("private invalid query");
  });

  it("keeps submitted runs available in local history", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(workflowPayload());

    render(<App />);

    fireEvent.click(
      screen.getByRole("button", { name: "Use sample question" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    await waitFor(() => {
      expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "History" }));

    expect(
      screen.getByRole("heading", { name: "Recent runs" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("loads review queue details and approves a selected review", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(reviewPayload())
      .mockResolvedValueOnce(reviewActionResponse());

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await screen.findByText("Version 0");
    expect(
      screen.getByText(
        "Generated draft includes medication-change language requiring review.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Rationale"), {
      target: { value: "Synthetic reviewer approval." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/v1/workflows/workflow-review-1/review-actions",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows stale review action errors safely", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(reviewPayload())
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            request_id: "request-3",
            error: {
              code: "stale_review_action",
              message: "The review action could not be applied.",
            },
          }),
          { status: 409 },
        ),
      );

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Version 0");
    fireEvent.change(screen.getByLabelText("Rationale"), {
      target: { value: "Synthetic reviewer approval." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "stale_review_action",
      );
    });
    expect(document.body).not.toHaveTextContent("private-code");
  });

  it("does not submit approval for pre-generation reviews without a draft", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      )
      .mockResolvedValueOnce(preGenerationReviewPayload());

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await screen.findByText(
      "This review paused before response generation. Approval is unavailable because there is no draft answer to finalize.",
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(
      screen.getByText("The request needs review before response generation."),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports an unavailable backend without hiding the application", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("backend unavailable"),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Backend: unavailable",
      );
    });
    expect(
      screen.getByRole("heading", { name: "AI Clinical Workflow Engine" }),
    ).toBeInTheDocument();
  });
});
