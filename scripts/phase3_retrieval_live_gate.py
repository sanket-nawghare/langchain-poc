"""Opt-in live Phase 3.5 retrieval gate over deidentified locked fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from app.core.config import Settings
from app.domain.base import ContractModel
from app.domain.guidelines import (
    EvidenceAssessment,
    GuidelineIdentifier,
    GuidelinePublisher,
    GuidelineQuery,
    GuidelineRetrievalRequest,
    GuidelineRetrievalResult,
)
from app.rag.retrieval import GuidelineRetrievalError, GuidelineRetriever
from app.rag.vector_store import GuidelineVectorStoreError
from app.services.deterministic_guideline_embeddings import (
    DeterministicGuidelineEmbeddingModel,
)
from app.services.deterministic_guideline_retrieval import (
    GUIDELINE_RETRIEVAL_POLICY_VERSION,
    DeterministicGuidelineRetriever,
    query_fingerprint,
)
from app.services.guideline_source_catalog import LockedGuidelineSourceCatalog
from app.services.local_weaviate import connect_local_async_weaviate
from app.services.pypdf_guidelines import PARSER_VERSION
from app.services.weaviate_guideline_candidates import (
    WeaviateGuidelineCandidateStore,
)

EVALUATION_CONTENT = "deidentified-guideline-retrieval-evaluation"
EVALUATION_SCHEMA_VERSION = 1
FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "_additional",
        "clinical_query",
        "patient_data",
        "patient_id",
        "patient_summary",
        "provider_payload",
        "vector",
    }
)
CaseId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    ),
]


class RetrievalEvaluationCase(ContractModel):
    """One deidentified expected retrieval outcome."""

    case_id: CaseId
    clinical_query: GuidelineQuery
    top_k: int = Field(ge=1, le=8)
    publishers: list[GuidelinePublisher] = Field(default_factory=list, max_length=4)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    expected_assessment: Literal["sufficient", "insufficient"]
    expected_document_id: GuidelineIdentifier | None
    expected_top_chunk_id: GuidelineIdentifier | None
    minimum_top_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_expectation(self) -> "RetrievalEvaluationCase":
        expected = (
            self.expected_document_id,
            self.expected_top_chunk_id,
            self.minimum_top_score,
        )
        if self.expected_assessment == "sufficient" and any(
            value is None for value in expected
        ):
            raise ValueError("sufficient fixture requires top-match expectations")
        if self.expected_assessment == "insufficient" and any(
            value is not None for value in expected
        ):
            raise ValueError("insufficient fixture must not expect a match")
        if len(set(self.publishers)) != len(self.publishers):
            raise ValueError("fixture publishers must be unique")
        return self


class RetrievalEvaluationSuite(ContractModel):
    """Strict policy-versioned deidentified evaluation fixture set."""

    schema_version: Literal[1]
    content: Literal["deidentified-guideline-retrieval-evaluation"]
    policy_version: Literal["deterministic-guideline-retrieval-v1"]
    cases: list[RetrievalEvaluationCase] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_cases(self) -> "RetrievalEvaluationSuite":
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case IDs must be unique")
        assessments = {case.expected_assessment for case in self.cases}
        if assessments != {"sufficient", "insufficient"}:
            raise ValueError("evaluation must cover sufficient and insufficient")
        return self


class RetrievalLiveGateError(RuntimeError):
    """A safe Phase 3.5 live retrieval assertion failed."""


def load_evaluation(path: Path) -> RetrievalEvaluationSuite:
    """Strictly load deidentified fixtures without accepting provider fields."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        suite = RetrievalEvaluationSuite.model_validate(value)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
    ) as error:
        raise RetrievalLiveGateError(
            "retrieval evaluation fixture is invalid"
        ) from error
    if suite.policy_version != GUIDELINE_RETRIEVAL_POLICY_VERSION:
        raise RetrievalLiveGateError("retrieval evaluation policy version differs")
    return suite


def validate_case_result(
    case: RetrievalEvaluationCase,
    result: GuidelineRetrievalResult,
) -> None:
    """Assert one result without logging its query, excerpts, or provider data."""

    if result.policy_version != GUIDELINE_RETRIEVAL_POLICY_VERSION:
        raise RetrievalLiveGateError("retrieval result policy version differs")
    if result.query_fingerprint != query_fingerprint(case.clinical_query):
        raise RetrievalLiveGateError("retrieval query fingerprint differs")
    if result.assessment.value != case.expected_assessment:
        raise RetrievalLiveGateError("retrieval assessment differs from fixture")
    serialized = result.model_dump(mode="json")
    if _all_keys(serialized) & FORBIDDEN_RESULT_KEYS:
        raise RetrievalLiveGateError("retrieval result contains forbidden fields")
    if case.clinical_query in json.dumps(serialized, sort_keys=True):
        raise RetrievalLiveGateError("retrieval result exposed its raw query")

    if result.assessment is EvidenceAssessment.INSUFFICIENT:
        if result.matches:
            raise RetrievalLiveGateError("insufficient result returned matches")
        return
    if not result.matches:
        raise RetrievalLiveGateError("sufficient result returned no matches")
    top = result.matches[0]
    if (
        top.source.document_id != case.expected_document_id
        or top.chunk.chunk_id != case.expected_top_chunk_id
        or top.relevance_score < (case.minimum_top_score or 0)
        or top.citation.document_id != top.source.document_id
        or top.citation.chunk_id != top.chunk.chunk_id
        or top.citation.page != top.chunk.page
        or top.citation.excerpt is None
    ):
        raise RetrievalLiveGateError("retrieval top match or citation differs")


async def evaluate_suite(
    retriever: GuidelineRetriever,
    suite: RetrievalEvaluationSuite,
) -> dict[str, object]:
    """Evaluate every fixture and return only aggregate safe metadata."""

    sufficient = 0
    insufficient = 0
    citation_count = 0
    for case in suite.cases:
        result = await retriever.retrieve(
            GuidelineRetrievalRequest(
                clinical_query=case.clinical_query,
                top_k=case.top_k,
                publishers=case.publishers,
                as_of=case.as_of,
            )
        )
        validate_case_result(case, result)
        if result.assessment is EvidenceAssessment.SUFFICIENT:
            sufficient += 1
            citation_count += len(result.matches)
        else:
            insufficient += 1
    return {
        "cases": len(suite.cases),
        "sufficient": sufficient,
        "insufficient": insufficient,
        "citations_verified": citation_count,
        "redaction": "verified",
        "policy_version": suite.policy_version,
    }


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for nested in value.values() for key in _all_keys(nested)
        }
    if isinstance(value, list):
        return {key for nested in value for key in _all_keys(nested)}
    return set()


async def run_gate(
    *,
    evaluation_path: Path,
    corpus_lock_path: Path,
) -> dict[str, object]:
    """Connect the real local adapters and evaluate the locked fixture suite."""

    suite = load_evaluation(evaluation_path)
    catalog = LockedGuidelineSourceCatalog(corpus_lock_path)
    settings = Settings()
    client = await connect_local_async_weaviate(settings)
    model = DeterministicGuidelineEmbeddingModel()
    candidate_store = WeaviateGuidelineCandidateStore(
        client,
        parser_version=PARSER_VERSION,
        embedding_model=model.model_id,
        embedding_dimensions=model.dimensions,
    )
    retriever = DeterministicGuidelineRetriever(
        catalog=catalog,
        embedding_model=model,
        candidate_store=candidate_store,
    )
    try:
        return await evaluate_suite(retriever, suite)
    finally:
        await retriever.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evaluation",
        type=Path,
        default=Path("data/guidelines/retrieval-evaluation.json"),
    )
    parser.add_argument(
        "--corpus-lock",
        type=Path,
        default=Path("data/guidelines/corpus-lock.json"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(
            run_gate(
                evaluation_path=args.evaluation,
                corpus_lock_path=args.corpus_lock,
            )
        )
    except (
        GuidelineRetrievalError,
        GuidelineVectorStoreError,
        RetrievalLiveGateError,
    ) as error:
        print(f"Phase 3.5 retrieval gate failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
