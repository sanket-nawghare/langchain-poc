"""Phase 3.5 retrieval evaluation and local connection safeguard tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from scripts.phase3_retrieval_live_gate import (
    RetrievalLiveGateError,
    load_evaluation,
    validate_case_result,
)
from weaviate.exceptions import WeaviateTimeoutError

from app.core.config import Settings
from app.domain import EvidenceAssessment, GuidelineRetrievalResult
from app.rag import (
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
)
from app.services.deterministic_guideline_retrieval import (
    GUIDELINE_RETRIEVAL_POLICY_VERSION,
    query_fingerprint,
)
from app.services.local_weaviate import connect_local_async_weaviate

EVALUATION_PATH = Path("data/guidelines/retrieval-evaluation.json")


def test_committed_evaluation_is_deidentified_strict_and_complete() -> None:
    suite = load_evaluation(EVALUATION_PATH)

    assert len(suite.cases) == 9
    assert sum(case.expected_assessment == "sufficient" for case in suite.cases) == 4
    assert sum(case.expected_assessment == "insufficient" for case in suite.cases) == 5
    serialized = EVALUATION_PATH.read_text(encoding="utf-8")
    assert "patient_id" not in serialized
    assert "patient_summary" not in serialized
    assert "excerpt" not in serialized
    assert "vector" not in serialized


def test_evaluation_rejects_provider_fields_and_duplicate_cases(
    tmp_path: Path,
) -> None:
    value = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    value["cases"][0]["_additional"] = {"provider": True}
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(RetrievalLiveGateError, match="invalid"):
        load_evaluation(path)

    value = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    value["cases"][1]["case_id"] = value["cases"][0]["case_id"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RetrievalLiveGateError, match="invalid"):
        load_evaluation(path)


def test_case_validation_accepts_insufficient_and_redacts_mismatch() -> None:
    case = next(
        case
        for case in load_evaluation(EVALUATION_PATH).cases
        if case.expected_assessment == "insufficient"
    )
    result = GuidelineRetrievalResult(
        assessment=EvidenceAssessment.INSUFFICIENT,
        policy_version=GUIDELINE_RETRIEVAL_POLICY_VERSION,
        query_fingerprint=query_fingerprint(case.clinical_query),
    )
    validate_case_result(case, result)

    changed = result.model_copy(update={"query_fingerprint": "0" * 64})
    with pytest.raises(RetrievalLiveGateError) as error:
        validate_case_result(case, changed)
    assert case.clinical_query not in str(error.value)


@pytest.mark.anyio
async def test_local_connection_rejects_non_loopback_url() -> None:
    settings = Settings(
        _env_file=None,
        weaviate_url="https://weaviate.example.test",
    )

    with pytest.raises(GuidelineVectorStoreSchemaError, match="loopback"):
        await connect_local_async_weaviate(settings)


@pytest.mark.anyio
async def test_local_connection_maps_timeout_and_closes_partial_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = type(
        "FakeAsyncWeaviateClient",
        (),
        {
            "connect": AsyncMock(side_effect=WeaviateTimeoutError("provider host")),
            "close": AsyncMock(),
        },
    )()
    monkeypatch.setattr(
        "app.services.local_weaviate.weaviate.use_async_with_custom",
        lambda **kwargs: client,
    )

    with pytest.raises(GuidelineVectorStoreTimeoutError) as error:
        await connect_local_async_weaviate(Settings(_env_file=None))

    assert "provider host" not in str(error.value)
    client.close.assert_awaited_once()


@pytest.mark.anyio
async def test_local_connection_uses_validated_loopback_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect = AsyncMock()
    client = SimpleNamespace(connect=connect, close=AsyncMock())
    captured: dict[str, object] = {}

    def fake_factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "app.services.local_weaviate.weaviate.use_async_with_custom",
        fake_factory,
    )
    settings = Settings(
        _env_file=None,
        weaviate_url="http://127.0.0.1:8081",
        weaviate_grpc_port=50051,
    )

    await connect_local_async_weaviate(settings)

    assert captured["http_host"] == "127.0.0.1"
    assert captured["http_port"] == 8081
    assert captured["grpc_port"] == 50051
    connect.assert_awaited_once()
