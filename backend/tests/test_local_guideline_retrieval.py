"""Lazy local workflow retrieval composition tests."""

import pytest

import app.services.local_guideline_retrieval as local_module
from app.core.config import Settings
from app.domain.guidelines import GuidelineRetrievalRequest, GuidelineRetrievalResult
from app.rag.retrieval import (
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
)
from app.rag.vector_store import (
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
)
from app.services.local_guideline_retrieval import LocalGuidelineRetriever
from tests.guideline_fixtures import sufficient_guideline_result


class StubDelegate:
    def __init__(self) -> None:
        self.requests: list[GuidelineRetrievalRequest] = []
        self.closed = False

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        self.requests.append(request)
        return sufficient_guideline_result()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_local_retriever_connects_lazily_reuses_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = 0
    delegate = StubDelegate()

    async def connect(settings: Settings) -> object:
        nonlocal connections
        del settings
        connections += 1
        return object()

    monkeypatch.setattr(local_module, "connect_local_async_weaviate", connect)
    monkeypatch.setattr(
        local_module,
        "LockedGuidelineSourceCatalog",
        lambda path: object(),
    )
    monkeypatch.setattr(
        local_module,
        "DeterministicGuidelineRetriever",
        lambda **kwargs: delegate,
    )
    retriever = LocalGuidelineRetriever(Settings(_env_file=None))
    request = GuidelineRetrievalRequest(
        clinical_query="What guidance applies to this synthetic condition?",
        as_of="2026-07-28",
    )

    first = await retriever.retrieve(request)
    second = await retriever.retrieve(request)
    await retriever.close()

    assert connections == 1
    assert first == second == sufficient_guideline_result()
    assert delegate.requests == [request, request]
    assert delegate.closed is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (GuidelineVectorStoreTimeoutError("sensitive"), GuidelineRetrievalTimeoutError),
        (
            GuidelineVectorStoreUnavailableError("sensitive"),
            GuidelineRetrievalUnavailableError,
        ),
        (GuidelineVectorStoreSchemaError("sensitive"), GuidelineRetrievalResponseError),
    ],
)
async def test_local_retriever_maps_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: Exception,
    expected_error: type[Exception],
) -> None:
    async def connect(settings: Settings) -> object:
        del settings
        raise provider_error

    monkeypatch.setattr(local_module, "connect_local_async_weaviate", connect)
    monkeypatch.setattr(
        local_module,
        "LockedGuidelineSourceCatalog",
        lambda path: object(),
    )
    retriever = LocalGuidelineRetriever(Settings(_env_file=None))
    request = GuidelineRetrievalRequest(
        clinical_query="What guidance applies to this synthetic condition?",
        as_of="2026-07-28",
    )

    with pytest.raises(expected_error) as captured:
        await retriever.retrieve(request)

    assert "sensitive" not in str(captured.value)
