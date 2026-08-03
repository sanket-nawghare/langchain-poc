"""Application-owned guideline retrieval capability and safe failures."""

from typing import Protocol

from app.domain.guidelines import GuidelineRetrievalRequest, GuidelineRetrievalResult


class GuidelineRetrievalError(RuntimeError):
    """Base retrieval failure safe to map beyond an adapter boundary."""


class GuidelineRetrievalTimeoutError(GuidelineRetrievalError):
    """Retrieval exhausted its bounded timeout behavior."""


class GuidelineRetrievalUnavailableError(GuidelineRetrievalError):
    """The retrieval dependency is unavailable."""


class GuidelineRetrievalResponseError(GuidelineRetrievalError):
    """A retrieval provider returned malformed or unsafe data."""


class GuidelineRetriever(Protocol):
    """Provider-neutral asynchronous clinical-guideline retrieval."""

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        """Return a normalized evidence decision or raise a typed safe failure."""
