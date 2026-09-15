"""Read-only normalized synthetic patient lookup endpoint."""

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.domain.api import ApiError, ApiSuccess, ErrorDetail
from app.domain.clinical import PatientSummary
from app.services.hapi_fhir import create_hapi_fhir_client
from app.services.patient_summary import (
    PatientSummaryService,
    create_patient_summary_service,
)
from app.tools.fhir import (
    FhirClientError,
    FhirNotFoundError,
    FhirRequestError,
    FhirResponseError,
    FhirTimeoutError,
    FhirUnavailableError,
)

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": ApiError},
    status.HTTP_404_NOT_FOUND: {"model": ApiError},
    status.HTTP_502_BAD_GATEWAY: {"model": ApiError},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiError},
}


async def patient_summary_service() -> AsyncIterator[PatientSummaryService]:
    """Provide a request-scoped summary service and close its HTTP transport."""

    settings = get_settings()
    async with create_hapi_fhir_client(settings) as client:
        yield create_patient_summary_service(settings, client)


def _error_response(
    *,
    request_id: UUID,
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
) -> JSONResponse:
    payload = ApiError(
        request_id=request_id,
        error=ErrorDetail(code=code, message=message, field=field),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


@router.get(
    "/{patient_id}/summary",
    response_model=ApiSuccess[PatientSummary],
    responses=ERROR_RESPONSES,
)
async def patient_summary(
    patient_id: str,
    service: Annotated[PatientSummaryService, Depends(patient_summary_service)],
) -> ApiSuccess[PatientSummary] | JSONResponse:
    """Return bounded normalized context for one synthetic FHIR patient."""

    request_id = uuid4()
    try:
        summary = await service.get(patient_id)
    except FhirRequestError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_patient_id",
            message="The synthetic patient ID is invalid.",
            field="patient_id",
        )
    except FhirNotFoundError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_404_NOT_FOUND,
            code="patient_not_found",
            message="The synthetic patient was not found.",
            field="patient_id",
        )
    except FhirTimeoutError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="fhir_timeout",
            message="The patient data service timed out.",
        )
    except FhirUnavailableError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="fhir_unavailable",
            message="The patient data service is unavailable.",
        )
    except FhirResponseError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="invalid_fhir_response",
            message="The patient data service returned an invalid response.",
        )
    except FhirClientError:
        return _error_response(
            request_id=request_id,
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="fhir_request_failed",
            message="The patient data request failed.",
        )

    return ApiSuccess(request_id=request_id, data=summary)
