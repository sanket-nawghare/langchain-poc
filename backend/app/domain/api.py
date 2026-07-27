"""Transport-neutral API success and error envelopes."""

from app.domain.base import ContractModel, CorrelationId, NonEmptyString


class ApiSuccess[PayloadT](ContractModel):
    """Successful API result with a request correlation identifier."""

    request_id: CorrelationId
    data: PayloadT


class ErrorDetail(ContractModel):
    """Stable machine code with a safe human-readable message."""

    code: NonEmptyString
    message: NonEmptyString
    field: NonEmptyString | None = None


class ApiError(ContractModel):
    """Failed API result without internal exception or secret details."""

    request_id: CorrelationId
    error: ErrorDetail
