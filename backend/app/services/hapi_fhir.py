"""Bounded asynchronous read-only HAPI FHIR transport."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.tools.fhir import (
    FhirNotFoundError,
    FhirRequestError,
    FhirResource,
    FhirResourceType,
    FhirResponseError,
    FhirSearchPage,
    FhirSearchParams,
    FhirTimeoutError,
    FhirUnavailableError,
)

FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,64}$")
SEARCH_PARAMETER_PATTERN = re.compile(r"^_?[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
FHIR_JSON_MEDIA_TYPE = "application/fhir+json"
SUPPORTED_RESOURCE_TYPES = frozenset(
    {
        "Patient",
        "Condition",
        "AllergyIntolerance",
        "MedicationRequest",
        "Encounter",
        "Observation",
        "Procedure",
        "DiagnosticReport",
    }
)


def _normalize_base_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    try:
        port = parsed.port
    except ValueError as error:
        raise FhirRequestError("FHIR base URL has an invalid port") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise FhirRequestError("FHIR base URL is not a safe HTTP endpoint")
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port is None else f"{hostname}:{port}"
    path = f"{parsed.path.rstrip('/')}/"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def _validate_resource_id(resource_id: str) -> None:
    if not FHIR_ID_PATTERN.fullmatch(resource_id):
        raise FhirRequestError("invalid FHIR resource ID")


def _validate_resource_type(resource_type: str) -> None:
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise FhirRequestError("unsupported FHIR resource type")


def _query_items(
    parameters: Mapping[str, str | Sequence[str]],
) -> httpx.QueryParams:
    items: list[tuple[str, str | int | float | bool | None]] = []
    for name, raw_values in parameters.items():
        if not SEARCH_PARAMETER_PATTERN.fullmatch(name):
            raise FhirRequestError("invalid FHIR search parameter")
        values = (raw_values,) if isinstance(raw_values, str) else tuple(raw_values)
        if not values:
            raise FhirRequestError("FHIR search parameter has no value")
        for value in values:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 512
                or any(character in value for character in "\r\n\0")
            ):
                raise FhirRequestError("invalid FHIR search value")
            if name == "_count" and (
                not value.isdecimal() or not 1 <= int(value) <= 100
            ):
                raise FhirRequestError("FHIR page size must be between 1 and 100")
            items.append((name, value))
    return httpx.QueryParams(items)


class HapiFhirClient:
    """HAPI adapter that exposes no write operations or HTTP response objects."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise FhirRequestError("FHIR timeout must be positive")
        if not 0 <= max_retries <= 3:
            raise FhirRequestError("FHIR max retries must be between 0 and 3")
        if not 0 <= retry_backoff_seconds <= 5:
            raise FhirRequestError("FHIR retry backoff must be between 0 and 5")
        self._base_url = httpx.URL(_normalize_base_url(base_url))
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = client or httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            headers={
                "Accept": FHIR_JSON_MEDIA_TYPE,
                "User-Agent": "clinical-workflow-fhir-client/0.1",
            },
        )
        self._owns_client = client is None

    async def __aenter__(self) -> HapiFhirClient:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only a transport created by this adapter."""

        if self._owns_client:
            await self._client.aclose()

    async def read(
        self,
        resource_type: FhirResourceType,
        resource_id: str,
    ) -> FhirResource:
        """Read and strictly parse one supported FHIR resource."""

        _validate_resource_type(resource_type)
        _validate_resource_id(resource_id)
        url = self._base_url.join(f"{resource_type}/{resource_id}")
        payload = await self._get_json(url)
        if (
            payload.get("resourceType") != resource_type
            or payload.get("id") != resource_id
        ):
            raise FhirResponseError("FHIR read returned an unexpected resource")
        return cast(FhirResource, payload)

    async def search(
        self,
        resource_type: FhirResourceType,
        parameters: FhirSearchParams,
    ) -> FhirSearchPage:
        """Search one supported resource type and parse its first page."""

        _validate_resource_type(resource_type)
        url = self._base_url.join(resource_type)
        payload = await self._get_json(url, params=_query_items(parameters))
        return self._parse_search_page(resource_type, payload)

    async def next_page(
        self,
        resource_type: FhirResourceType,
        cursor: str,
    ) -> FhirSearchPage:
        """Follow only a server cursor confined beneath this FHIR base URL."""

        _validate_resource_type(resource_type)
        url = self._validated_page_url(resource_type, cursor)
        payload = await self._get_json(url)
        return self._parse_search_page(resource_type, payload)

    async def _get_json(
        self,
        url: httpx.URL,
        *,
        params: httpx.QueryParams | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    timeout=self._timeout,
                    headers={"Accept": FHIR_JSON_MEDIA_TYPE},
                )
            except httpx.TimeoutException as error:
                if attempt == self._max_retries:
                    raise FhirTimeoutError(
                        "FHIR request timed out after bounded retries"
                    ) from error
                await self._backoff(attempt)
                continue
            except httpx.TransportError as error:
                if attempt == self._max_retries:
                    raise FhirUnavailableError(
                        "FHIR service is unavailable after bounded retries"
                    ) from error
                await self._backoff(attempt)
                continue

            if response.status_code == 404:
                raise FhirNotFoundError("FHIR resource was not found")
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == self._max_retries:
                    raise FhirUnavailableError(
                        "FHIR service remained unavailable after bounded retries"
                    )
                await self._backoff(attempt)
                continue
            if response.is_redirect or response.is_error:
                raise FhirResponseError(
                    f"FHIR service returned HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as error:
                raise FhirResponseError("FHIR service returned invalid JSON") from error
            if not isinstance(payload, dict):
                raise FhirResponseError("FHIR service returned non-object JSON")
            return cast(dict[str, Any], payload)
        raise AssertionError("unreachable retry state")

    async def _backoff(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        if delay:
            await asyncio.sleep(delay)

    def _parse_search_page(
        self,
        resource_type: FhirResourceType,
        payload: dict[str, Any],
    ) -> FhirSearchPage:
        if (
            payload.get("resourceType") != "Bundle"
            or payload.get("type") != "searchset"
        ):
            raise FhirResponseError("FHIR search returned an unexpected resource")

        total = payload.get("total")
        if total is not None and (type(total) is not int or total < 0):
            raise FhirResponseError("FHIR search returned an invalid total")

        raw_entries = payload.get("entry", [])
        if not isinstance(raw_entries, list):
            raise FhirResponseError("FHIR search returned invalid entries")
        resources: list[FhirResource] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise FhirResponseError("FHIR search returned an invalid entry")
            resource = raw_entry.get("resource")
            resource_id = resource.get("id") if isinstance(resource, dict) else None
            if (
                not isinstance(resource, dict)
                or resource.get("resourceType") != resource_type
                or not isinstance(resource_id, str)
                or not FHIR_ID_PATTERN.fullmatch(resource_id)
            ):
                raise FhirResponseError("FHIR search returned an unexpected entry")
            resources.append(cast(FhirResource, resource))

        next_cursor: str | None = None
        raw_links = payload.get("link", [])
        if not isinstance(raw_links, list):
            raise FhirResponseError("FHIR search returned invalid links")
        for raw_link in raw_links:
            if not isinstance(raw_link, dict) or raw_link.get("relation") != "next":
                continue
            link_url = raw_link.get("url")
            if not isinstance(link_url, str):
                raise FhirResponseError("FHIR next link is invalid")
            next_cursor = str(self._validated_page_url(resource_type, link_url))
            break
        return FhirSearchPage(
            resources=tuple(resources),
            total=total,
            next_cursor=next_cursor,
        )

    def _validated_page_url(
        self,
        resource_type: FhirResourceType,
        cursor: str,
    ) -> httpx.URL:
        try:
            candidate = self._base_url.join(cursor)
        except (TypeError, ValueError) as error:
            raise FhirResponseError("FHIR next link is invalid") from error
        same_origin = (
            candidate.scheme == self._base_url.scheme
            and candidate.host == self._base_url.host
            and candidate.port == self._base_url.port
        )
        base_path = self._base_url.path.rstrip("/")
        resource_path = f"{base_path}/{resource_type}"
        root_page = (
            candidate.path.rstrip("/") == base_path and "_getpages" in candidate.params
        )
        if (
            not same_origin
            or (candidate.path.rstrip("/") != resource_path and not root_page)
            or candidate.fragment
            or candidate.userinfo
        ):
            raise FhirResponseError("FHIR next link escaped the configured base URL")
        return candidate


def create_hapi_fhir_client(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> HapiFhirClient:
    """Create the adapter from validated application settings."""

    return HapiFhirClient(
        base_url=str(settings.fhir_base_url),
        timeout_seconds=settings.fhir_request_timeout_seconds,
        max_retries=settings.fhir_max_retries,
        retry_backoff_seconds=settings.fhir_retry_backoff_seconds,
        client=client,
    )
