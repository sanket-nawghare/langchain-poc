"""Normalized patient-context and citation contracts."""

from typing import Literal

from pydantic import AnyHttpUrl, Field

from app.domain.base import ContractModel, NonEmptyString, PatientId

type ClinicalSummaryCategory = Literal[
    "conditions",
    "allergies",
    "medications",
    "encounters",
    "observations",
    "procedures",
    "diagnostic_reports",
]


class ClinicalRecordSummary(ContractModel):
    """Small normalized description of a relevant FHIR record."""

    code: NonEmptyString | None = None
    display: NonEmptyString
    status: NonEmptyString | None = None
    effective_at: str | None = None
    value: NonEmptyString | None = None


class PatientSummary(ContractModel):
    """Minimum patient context allowed to cross the FHIR adapter boundary."""

    patient_id: PatientId
    display_name: NonEmptyString | None = None
    conditions: list[ClinicalRecordSummary] = Field(default_factory=list)
    allergies: list[ClinicalRecordSummary] = Field(default_factory=list)
    medications: list[ClinicalRecordSummary] = Field(default_factory=list)
    encounters: list[ClinicalRecordSummary] = Field(default_factory=list)
    observations: list[ClinicalRecordSummary] = Field(default_factory=list)
    procedures: list[ClinicalRecordSummary] = Field(default_factory=list)
    diagnostic_reports: list[ClinicalRecordSummary] = Field(default_factory=list)
    truncated_categories: list[ClinicalSummaryCategory] = Field(default_factory=list)


class Citation(ContractModel):
    """Traceable evidence location for a guideline-backed statement."""

    document_id: NonEmptyString
    chunk_id: NonEmptyString
    title: NonEmptyString
    publisher: NonEmptyString
    source_url: AnyHttpUrl
    page: int | None = Field(default=None, ge=1)
    excerpt: NonEmptyString | None = None
