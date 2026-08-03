"""Application-owned structured response-generation capability."""

from typing import Protocol

from app.domain.generation import GroundedGenerationRequest, ResponseGenerationResult


class ResponseGenerationError(RuntimeError):
    """The response generator could not return a safe structured draft."""

    reason_code = "provider_failure"


class ResponseGenerationTimeoutError(ResponseGenerationError):
    """The response generator exhausted its bounded execution time."""

    reason_code = "provider_timeout"


class ResponseGenerationUnavailableError(ResponseGenerationError):
    """The configured response provider is temporarily unavailable."""

    reason_code = "provider_unavailable"


class ResponseGenerationAuthenticationError(ResponseGenerationError):
    """The configured response-provider credentials were rejected."""

    reason_code = "provider_authentication"


class ResponseGenerationRateLimitError(ResponseGenerationError):
    """The response provider rejected the bounded request due to a rate limit."""

    reason_code = "provider_rate_limit"


class ResponseGenerationRequestError(ResponseGenerationError):
    """The provider rejected the bounded request before producing output."""

    reason_code = "provider_request_rejected"


class ResponseGenerationInputError(ResponseGenerationError):
    """Application-owned grounded input could not be built safely."""

    reason_code = "invalid_grounded_input"


class ResponseGenerationMalformedOutputError(ResponseGenerationError):
    """The provider returned output outside the application-owned contract."""

    reason_code = "invalid_structured_output"


class ResponseGenerationIncompleteOutputError(ResponseGenerationMalformedOutputError):
    """The provider did not return exactly one answer message."""

    reason_code = "incomplete_provider_output"


class ResponseGenerationUnexpectedOutputError(ResponseGenerationMalformedOutputError):
    """The provider returned an output item outside the no-tools contract."""

    reason_code = "unexpected_provider_output"


class ResponseGenerationMissingAnswerError(ResponseGenerationMalformedOutputError):
    """The structured provider output omitted the required answer."""

    reason_code = "missing_provider_answer"


class ResponseGenerationOversizedAnswerError(ResponseGenerationMalformedOutputError):
    """The structured provider answer exceeded the application limit."""

    reason_code = "oversized_provider_answer"


class ResponseGenerationUnexpectedFieldsError(ResponseGenerationMalformedOutputError):
    """The structured provider output attempted to add owned fields."""

    reason_code = "unexpected_provider_fields"


class ResponseGenerationInvalidAnswerTypeError(ResponseGenerationMalformedOutputError):
    """The structured provider answer was not text."""

    reason_code = "invalid_provider_answer_type"


class ResponseGenerationContextLimitError(ResponseGenerationError):
    """The provider rejected input that exceeded its context limit."""

    reason_code = "provider_context_limit"


class ResponseGenerationRefusalError(ResponseGenerationError):
    """The provider explicitly refused to produce a structured draft."""

    reason_code = "provider_refusal"


class ResponseGenerator(Protocol):
    """Draft bounded educational text without controlling qualifications."""

    async def generate(
        self,
        *,
        request: GroundedGenerationRequest,
    ) -> ResponseGenerationResult:
        """Return a strict draft and bounded provider-neutral metadata."""
