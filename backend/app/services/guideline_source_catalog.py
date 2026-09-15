"""Strict source-only catalog backed by the committed guideline corpus lock."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from app.domain.guidelines import GuidelineSource
from app.rag.retrieval import GuidelineRetrievalResponseError

CORPUS_LOCK_CONTENT = "reviewed-guideline-provenance-and-checksums-only"
CORPUS_LOCK_SCHEMA_VERSION = 1
MAX_CATALOG_SOURCES = 8

JsonObject = dict[str, Any]


class LockedGuidelineSourceCatalog:
    """Load immutable reviewed source identities without reading document content."""

    def __init__(self, lock_path: Path) -> None:
        self._sources = _load_sources(lock_path)

    def sources(self) -> tuple[GuidelineSource, ...]:
        return self._sources


def _load_sources(lock_path: Path) -> tuple[GuidelineSource, ...]:
    try:
        value = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuidelineRetrievalResponseError(
            "trusted guideline source catalog is invalid"
        ) from error
    root = _mapping(value, label="catalog")
    _exact_keys(root, {"schema_version", "content", "documents"}, label="catalog")
    if (
        root["schema_version"] != CORPUS_LOCK_SCHEMA_VERSION
        or root["content"] != CORPUS_LOCK_CONTENT
    ):
        raise GuidelineRetrievalResponseError(
            "trusted guideline source catalog version is unsupported"
        )

    documents = _sequence(root["documents"], label="catalog documents")
    if not documents or len(documents) > MAX_CATALOG_SOURCES:
        raise GuidelineRetrievalResponseError(
            "trusted guideline source count is outside bounds"
        )

    sources: list[GuidelineSource] = []
    for index, value in enumerate(documents):
        document = _mapping(value, label=f"catalog documents[{index}]")
        _exact_keys(
            document,
            {"source", "artifact", "supported_scenarios"},
            label=f"catalog documents[{index}]",
        )
        # Validate the unused envelopes so provider fields cannot hide beside a source.
        artifact = _mapping(
            document["artifact"],
            label=f"catalog documents[{index}].artifact",
        )
        _exact_keys(
            artifact,
            {"download_url", "filename", "page_count", "size_bytes"},
            label=f"catalog documents[{index}].artifact",
        )
        scenarios = _sequence(
            document["supported_scenarios"],
            label=f"catalog documents[{index}].supported_scenarios",
        )
        if not scenarios or not all(
            isinstance(scenario, str) and scenario.strip() for scenario in scenarios
        ):
            raise GuidelineRetrievalResponseError(
                "trusted guideline source scenarios are invalid"
            )
        try:
            source = GuidelineSource.model_validate(document["source"])
        except ValidationError as error:
            raise GuidelineRetrievalResponseError(
                "trusted guideline source record is invalid"
            ) from error
        if not source.is_indexable:
            raise GuidelineRetrievalResponseError(
                "trusted guideline source is not approved for indexing"
            )
        sources.append(source)

    if len({source.document_id for source in sources}) != len(sources):
        raise GuidelineRetrievalResponseError(
            "trusted guideline source IDs are not unique"
        )
    return tuple(sorted(sources, key=lambda source: source.document_id))


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise GuidelineRetrievalResponseError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise GuidelineRetrievalResponseError(f"{label} must be an array")
    return cast(Sequence[object], value)


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(value) != expected:
        raise GuidelineRetrievalResponseError(
            f"{label} has unexpected or missing fields"
        )
