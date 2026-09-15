"""Deterministic local embeddings for repeatable development ingestion."""

import hashlib
import math
import re
from collections.abc import Sequence

from app.rag.embeddings import GuidelineEmbeddingResponseError

DETERMINISTIC_EMBEDDING_MODEL = "deterministic-token-hash-v1"
DETERMINISTIC_EMBEDDING_DIMENSIONS = 128
MAX_EMBEDDING_BATCH = 256
MAX_EMBEDDING_TEXT_LENGTH = 3000
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)?")


class DeterministicGuidelineEmbeddingModel:
    """Hash normalized tokens into fixed-width, unit-length local vectors."""

    @property
    def model_id(self) -> str:
        return DETERMINISTIC_EMBEDDING_MODEL

    @property
    def dimensions(self) -> int:
        return DETERMINISTIC_EMBEDDING_DIMENSIONS

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts or len(texts) > MAX_EMBEDDING_BATCH:
            raise GuidelineEmbeddingResponseError(
                "embedding batch count is outside bounds"
            )
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        if not text or len(text) > MAX_EMBEDDING_TEXT_LENGTH:
            raise GuidelineEmbeddingResponseError(
                "embedding text length is outside bounds"
            )
        tokens = _TOKEN_PATTERN.findall(text.casefold())
        if not tokens:
            raise GuidelineEmbeddingResponseError("embedding text contains no tokens")

        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise GuidelineEmbeddingResponseError("embedding vector has zero norm")
        return tuple(value / norm for value in vector)
