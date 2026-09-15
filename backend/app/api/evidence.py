"""Browser-openable evidence references for local synthetic workflow outputs."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("/synthetic-patient-summary", response_class=HTMLResponse)
async def synthetic_patient_summary_evidence() -> HTMLResponse:
    """Describe the local patient-summary citation without exposing raw FHIR."""

    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <title>Synthetic patient summary evidence</title>
            <style>
              body {
                color: #17252a;
                font-family:
                  Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
                  "Segoe UI", sans-serif;
                line-height: 1.5;
                margin: 0;
                padding: 32px;
              }

              main {
                max-width: 760px;
              }

              code {
                background: #eef3f4;
                border-radius: 6px;
                padding: 2px 6px;
              }
            </style>
          </head>
          <body>
            <main>
              <p>Synthetic data only</p>
              <h1>Synthetic patient summary evidence</h1>
              <p>
                This citation represents bounded, normalized patient context read
                from the local HAPI FHIR service and projected by the backend patient
                summary adapter.
              </p>
              <p>
                It is not an external guideline document and it does not expose the
                raw FHIR resource payload. The workflow response includes the
                specific bounded excerpt used for the answer.
              </p>
              <p>Current supported local category: <code>allergies</code>.</p>
            </main>
          </body>
        </html>
        """
    )
