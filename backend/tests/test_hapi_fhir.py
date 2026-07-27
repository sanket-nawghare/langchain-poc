"""Bounded read-only HAPI FHIR adapter tests."""

from typing import cast

import httpx
import pytest

from app.services.hapi_fhir import HapiFhirClient
from app.tools.fhir import (
    FhirNotFoundError,
    FhirRequestError,
    FhirResourceType,
    FhirResponseError,
    FhirTimeoutError,
    FhirUnavailableError,
)


def adapter(
    client: httpx.AsyncClient,
    *,
    max_retries: int = 2,
) -> HapiFhirClient:
    return HapiFhirClient(
        base_url="https://hapi.test/fhir",
        timeout_seconds=1,
        max_retries=max_retries,
        retry_backoff_seconds=0,
        client=client,
    )


@pytest.mark.anyio
async def test_reads_a_supported_resource_with_fhir_json_negotiation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/fhir/Patient/patient-1"
        assert request.headers["accept"] == "application/fhir+json"
        return httpx.Response(
            200,
            json={"resourceType": "Patient", "id": "patient-1"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resource = await adapter(client).read("Patient", "patient-1")

    assert resource == {"resourceType": "Patient", "id": "patient-1"}


@pytest.mark.anyio
async def test_parses_search_pages_and_confined_next_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            assert request.url.path == "/fhir/Observation"
            assert request.url.params["patient"] == "patient-1"
            assert request.url.params["_count"] == "20"
            payload = {
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 2,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "observation-1",
                        }
                    }
                ],
                "link": [
                    {
                        "relation": "next",
                        "url": "https://hapi.test/fhir?_getpages=opaque",
                    }
                ],
            }
        else:
            assert request.url.path == "/fhir"
            assert request.url.params["_getpages"] == "opaque"
            payload = {
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 2,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "observation-2",
                        }
                    }
                ],
            }
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fhir = adapter(client)
        first = await fhir.search(
            "Observation",
            {"patient": "patient-1", "_count": "20"},
        )
        assert first.next_cursor is not None
        second = await fhir.next_page("Observation", first.next_cursor)

    assert first.total == 2
    assert first.resources[0]["id"] == "observation-1"
    assert second.resources[0]["id"] == "observation-2"
    assert second.next_cursor is None


@pytest.mark.anyio
async def test_rejects_next_link_that_escapes_the_fhir_base() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "link": [
                    {
                        "relation": "next",
                        "url": "https://attacker.example/fhir/Observation?page=2",
                    }
                ],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FhirResponseError, match="escaped"):
            await adapter(client).search("Observation", {"patient": "patient-1"})


@pytest.mark.anyio
async def test_maps_not_found_without_exposing_response_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "resourceType": "OperationOutcome",
                "issue": [{"diagnostics": "sensitive upstream diagnostics"}],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FhirNotFoundError) as error:
            await adapter(client).read("Patient", "missing")

    assert "sensitive upstream diagnostics" not in str(error.value)


@pytest.mark.anyio
async def test_retries_timeouts_with_a_fixed_upper_bound() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("sensitive timeout details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FhirTimeoutError) as error:
            await adapter(client, max_retries=2).read("Patient", "patient-1")

    assert attempts == 3
    assert "sensitive timeout details" not in str(error.value)


@pytest.mark.anyio
async def test_retries_retryable_status_then_reports_unavailable() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FhirUnavailableError):
            await adapter(client, max_retries=1).read("Patient", "patient-1")

    assert attempts == 2


@pytest.mark.anyio
async def test_rejects_malformed_or_unexpected_fhir_json() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b"not-json"),
            httpx.Response(
                200,
                json={"resourceType": "Observation", "id": "patient-1"},
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fhir = adapter(client)
        with pytest.raises(FhirResponseError, match="invalid JSON"):
            await fhir.read("Patient", "patient-1")
        with pytest.raises(FhirResponseError, match="unexpected resource"):
            await fhir.read("Patient", "patient-1")


@pytest.mark.anyio
async def test_rejects_unbounded_or_unsupported_requests_before_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unsafe request reached transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fhir = adapter(client)
        with pytest.raises(FhirRequestError, match="resource ID"):
            await fhir.read("Patient", "../Observation")
        with pytest.raises(FhirRequestError, match="unsupported"):
            await fhir.read(cast(FhirResourceType, "Claim"), "claim-1")
        with pytest.raises(FhirRequestError, match="page size"):
            await fhir.search("Observation", {"_count": "1000"})


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/fhir",
        "https://user:secret@hapi.test/fhir",
        "https://hapi.test/fhir?unsafe=true",
        "https://hapi.test/fhir#fragment",
    ],
)
def test_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(FhirRequestError, match="safe HTTP endpoint"):
        HapiFhirClient(
            base_url=base_url,
            timeout_seconds=1,
            max_retries=0,
            retry_backoff_seconds=0,
        )
