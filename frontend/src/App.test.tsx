import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the foundation shell and reports an available backend", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "AI Clinical Workflow Engine" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a medical device/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Backend: available");
    });
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

