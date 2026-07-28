"""Shared contract primitives and validation behavior."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
PatientId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9.-]+$",
    ),
]
WorkflowQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
WorkflowId = UUID
CorrelationId = UUID
AuditEventId = UUID
UtcTimestamp = Annotated[datetime, AwareDatetime()]


class ContractModel(BaseModel):
    """Strict base for durable application contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class IdentifiedAt(ContractModel):
    """Common identifier and timestamp fields for persisted records."""

    id: UUID
    created_at: UtcTimestamp = Field(description="Timezone-aware UTC timestamp")
