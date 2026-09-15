"""Local evidence-link API tests."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_synthetic_patient_summary_evidence_page_is_browser_openable(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/evidence/synthetic-patient-summary")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Synthetic patient summary evidence" in response.text
    assert "raw FHIR resource payload" in response.text
    assert "resourceType" not in response.text
    assert "Patient/" not in response.text
