"""Workflow-facing normalized patient summary capability."""

from typing import Protocol

from app.domain.clinical import PatientSummary


class PatientSummaryError(RuntimeError):
    """A normalized patient result violated the application contract."""


class PatientSummaryReader(Protocol):
    """Read minimum-necessary patient context without exposing raw FHIR."""

    async def get(self, patient_id: str) -> PatientSummary:
        """Return a validated normalized summary for one synthetic patient."""
