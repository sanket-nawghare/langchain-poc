import { useEffect, useState } from "react";

type ApiStatus = "checking" | "available" | "unavailable";

const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();

    async function checkApi() {
      try {
        const response = await fetch(`${apiBaseUrl}/health/live`, {
          signal: controller.signal,
        });
        setApiStatus(response.ok ? "available" : "unavailable");
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          setApiStatus("unavailable");
        }
      }
    }

    void checkApi();
    return () => controller.abort();
  }, []);

  return (
    <main className="shell">
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">Synthetic data only</p>
        <h1 id="page-title">AI Clinical Workflow Engine</h1>
        <p className="summary">
          An educational environment for inspecting clinical AI workflow
          orchestration. It is not a medical device.
        </p>
        <div className={`status status--${apiStatus}`} role="status">
          <span aria-hidden="true" className="status__indicator" />
          Backend: {apiStatus}
        </div>
      </section>
    </main>
  );
}

