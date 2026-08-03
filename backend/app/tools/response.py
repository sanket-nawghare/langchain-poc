"""Application-owned structured response-generation capability."""

from typing import Protocol

from app.domain.generation import GroundedGenerationRequest, ResponseGenerationResult


class ResponseGenerationError(RuntimeError):
    """The response generator could not return a safe structured draft."""


class ResponseGenerationTimeoutError(ResponseGenerationError):
    """The response generator exhausted its bounded execution time."""


class ResponseGenerationUnavailableError(ResponseGenerationError):
    """The configured response provider is temporarily unavailable."""


class ResponseGenerationAuthenticationError(ResponseGenerationError):
    """The configured response-provider credentials were rejected."""


class ResponseGenerationRateLimitError(ResponseGenerationError):
    """The response provider rejected the bounded request due to a rate limit."""


class ResponseGenerationMalformedOutputError(ResponseGenerationError):
    """The provider returned output outside the application-owned contract."""


class ResponseGenerationContextLimitError(ResponseGenerationError):
    """The provider rejected input that exceeded its context limit."""


class ResponseGenerationRefusalError(ResponseGenerationError):
    """The provider explicitly refused to produce a structured draft."""


class ResponseGenerator(Protocol):
    """Draft bounded educational text without controlling qualifications."""

    async def generate(
        self,
        *,
        request: GroundedGenerationRequest,
    ) -> ResponseGenerationResult:
        """Return a strict draft and bounded provider-neutral metadata."""
