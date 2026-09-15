"""Lazy request-scoped local guideline-retrieval composition."""

from app.core.config import Settings
from app.domain.guidelines import GuidelineRetrievalRequest, GuidelineRetrievalResult
from app.rag.retrieval import (
    GuidelineRetrievalResponseError,
    GuidelineRetrievalTimeoutError,
    GuidelineRetrievalUnavailableError,
    GuidelineRetriever,
)
from app.rag.vector_store import (
    GuidelineVectorStoreError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
)
from app.services.deterministic_guideline_embeddings import (
    DeterministicGuidelineEmbeddingModel,
)
from app.services.deterministic_guideline_retrieval import (
    DeterministicGuidelineRetriever,
)
from app.services.guideline_source_catalog import LockedGuidelineSourceCatalog
from app.services.local_weaviate import connect_local_async_weaviate
from app.services.pypdf_guidelines import PARSER_VERSION
from app.services.weaviate_guideline_candidates import (
    WeaviateGuidelineCandidateStore,
)


class LocalGuidelineRetriever:
    """Lazily connect reviewed local components behind the retrieval protocol."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._delegate: GuidelineRetriever | None = None

    async def _connect(self) -> GuidelineRetriever:
        if self._delegate is not None:
            return self._delegate
        try:
            catalog = LockedGuidelineSourceCatalog(
                self._settings.guideline_corpus_lock_path
            )
            client = await connect_local_async_weaviate(self._settings)
        except GuidelineVectorStoreTimeoutError as error:
            raise GuidelineRetrievalTimeoutError(
                "local guideline retrieval timed out"
            ) from error
        except GuidelineVectorStoreUnavailableError as error:
            raise GuidelineRetrievalUnavailableError(
                "local guideline retrieval is unavailable"
            ) from error
        except GuidelineVectorStoreError as error:
            raise GuidelineRetrievalResponseError(
                "local guideline retrieval configuration is invalid"
            ) from error

        model = DeterministicGuidelineEmbeddingModel()
        candidate_store = WeaviateGuidelineCandidateStore(
            client,
            parser_version=PARSER_VERSION,
            embedding_model=model.model_id,
            embedding_dimensions=model.dimensions,
        )
        self._delegate = DeterministicGuidelineRetriever(
            catalog=catalog,
            embedding_model=model,
            candidate_store=candidate_store,
        )
        return self._delegate

    async def retrieve(
        self,
        request: GuidelineRetrievalRequest,
    ) -> GuidelineRetrievalResult:
        """Retrieve from the lazily connected local reviewed index."""

        delegate = await self._connect()
        return await delegate.retrieve(request)

    async def close(self) -> None:
        """Close the local client only when this request opened one."""

        if self._delegate is not None:
            await self._delegate.close()
            self._delegate = None
