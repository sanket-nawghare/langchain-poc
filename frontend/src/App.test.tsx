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
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(
      screen.getByText("Reviewed synthetic guideline"),
    ).toBeInTheDocument();
    expect(screen.getByText("finalize response")).toBeInTheDocument();
    expect(screen.getByText("response generated")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("patient_data");
    expect(document.body).not.toHaveTextContent("private-code");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/v1/workflows",
      expect.objectContaining({ method: "POST" }),
    );
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
      expect(screen.getByText("pending review")).toBeInTheDocument();
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

    await screen.findByText("completed");
    fireEvent.click(screen.getByRole("button", { name: "History" }));

    expect(
      screen.getByRole("heading", { name: "Recent runs" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
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
