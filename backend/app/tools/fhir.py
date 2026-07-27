"""Application-owned read-only FHIR capability contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type FhirResource = dict[str, JsonValue]
type FhirResourceType = Literal[
    "Patient",
    "Condition",
    "AllergyIntolerance",
    "MedicationRequest",
    "Encounter",
    "Observation",
    "Procedure",
    "DiagnosticReport",
]
type FhirSearchValue = str | tuple[str, ...]
type FhirSearchParams = dict[str, FhirSearchValue]


class FhirClientError(RuntimeError):
    """Base error safe to propagate beyond the HAPI adapter."""


class FhirRequestError(FhirClientError):
    """The application supplied an invalid bounded FHIR request."""


class FhirNotFoundError(FhirClientError):
    """The requested FHIR resource does not exist."""


class FhirTimeoutError(FhirClientError):
    """The FHIR service exhausted its bounded timeout retries."""


class FhirUnavailableError(FhirClientError):
    """The FHIR service is unavailable after bounded retries."""


class FhirResponseError(FhirClientError):
    """The FHIR service returned an unsafe or malformed response."""


@dataclass(frozen=True)
class FhirSearchPage:
    """Parsed FHIR search page without HTTP-library response objects."""

    resources: tuple[FhirResource, ...]
    total: int | None
    next_cursor: str | None


class FhirClient(Protocol):
    """Read-only FHIR operations exposed to application services."""

    async def read(
        self,
        resource_type: FhirResourceType,
        resource_id: str,
    ) -> FhirResource:
        """Read one resource by its stable FHIR ID."""

    async def search(
        self,
        resource_type: FhirResourceType,
        parameters: FhirSearchParams,
    ) -> FhirSearchPage:
        """Read the first page of a bounded resource search."""

    async def next_page(
        self,
        resource_type: FhirResourceType,
        cursor: str,
    ) -> FhirSearchPage:
        """Read a server-issued next page confined to the FHIR base URL."""

    async def aclose(self) -> None:
        """Release adapter-owned transport resources."""
