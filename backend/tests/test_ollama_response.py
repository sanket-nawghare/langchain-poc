"""Ollama grounded response adapter tests without external model calls."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.domain.clinical import Citation, ClinicalRecordSummary, PatientSummary
from app.domain.generation import GroundedGenerationRequest
from app.domain.workflow import ResponseDraft
from app.services.grounded_generation import build_grounded_generation_request
from app.services.ollama_response import (
    OllamaResponseGenerator,
    create_ollama_response_generator,
)
from app.tools.response import (
    ResponseGenerationContextLimitError,
    ResponseGenerationMalformedOutputError,
    ResponseGenerationRateLimitError,
    ResponseGenerationRequestError,
    ResponseGenerationTimeoutError,
    ResponseGenerationUnavailableError,
    ResponseGenerator,
)


def grounded_request() -> GroundedGenerationRequest:
    return build_grounded_generation_request(
        query="What does the evidence support?",
        patient=PatientSummary(
            patient_id="synthetic-patient-private-id",
            display_name="Private synthetic display name",
            conditions=[ClinicalRecordSummary(display="Synthetic condition")],
        ),
        guidelines=[
            Citation(
                document_id="guideline-1",
                chunk_id="chunk-1",
                title="Synthetic guideline",
                publisher="Example publisher",
                source_url="https://example.test/guideline",
                page=2,
                excerpt="Trusted bounded evidence.",
            )
        ],
    )


def accepts_response_generator(value: ResponseGenerator) -> ResponseGenerator:
    return value


def generator(
    handler: httpx.AsyncBaseTransport,
) -> tuple[OllamaResponseGenerator, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        base_url="http://localhost:11434",
        transport=handler,
    )
    return (
        OllamaResponseGenerator(
            client=client,
            model="qwen3:4b",
            max_output_tokens=2048,
            context_window=8192,
        ),
        client,
    )


@pytest.mark.anyio
async def test_ollama_adapter_uses_schema_and_returns_strict_draft() -> None:
    captured: dict[str, object] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "A bounded grounded answer."}),
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 123,
                "eval_count": 45,
            },
        )

    adapter, _ = generator(httpx.MockTransport(handle))
    assert accepts_response_generator(adapter) is adapter

    result = await adapter.generate(request=grounded_request())

    assert result.draft == ResponseDraft(answer="A bounded grounded answer.")
    assert result.metadata.model_alias == "qwen3:4b"
    assert result.metadata.input_tokens == 123
    assert result.metadata.output_tokens == 45
    assert captured["model"] == "qwen3:4b"
    assert captured["stream"] is False
    assert captured["think"] is False
    assert captured["format"] == ResponseDraft.model_json_schema()
    assert captured["options"] == {
        "temperature": 0,
        "num_predict": 2048,
        "num_ctx": 8192,
    }
    messages = str(captured["messages"])
    assert "synthetic-patient-private-id" not in messages
    assert "Private synthetic display name" not in messages
    assert "Trusted bounded evidence" in messages
    await adapter.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content", "done_reason"),
    [
        ("not-json", "stop"),
        (json.dumps({"answer": "x" * 4001}), "stop"),
        (json.dumps({"answer": "Draft", "citations": []}), "stop"),
    ],
)
async def test_ollama_adapter_rejects_invalid_structured_output(
    content: str,
    done_reason: str,
) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": content},
                "done": True,
                "done_reason": done_reason,
            },
        )

    adapter, _ = generator(httpx.MockTransport(handle))
    with pytest.raises(ResponseGenerationMalformedOutputError):
        await adapter.generate(request=grounded_request())
    await adapter.close()


@pytest.mark.anyio
async def test_ollama_adapter_accepts_slow_valid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([1000.0, 1176.0])
    monkeypatch.setattr(
        "app.services.ollama_response.perf_counter", lambda: next(ticks)
    )

    async def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "A slow grounded answer."}),
                },
                "done": True,
                "done_reason": "stop",
            },
        )

    adapter, _ = generator(httpx.MockTransport(handle))
    result = await adapter.generate(request=grounded_request())

    assert result.draft == ResponseDraft(answer="A slow grounded answer.")
    assert result.metadata.latency_ms == 176_000
    await adapter.close()


@pytest.mark.anyio
async def test_ollama_adapter_maps_output_limit() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"message": {"content": ""}, "done_reason": "length"},
        )

    adapter, _ = generator(httpx.MockTransport(handle))
    with pytest.raises(ResponseGenerationContextLimitError):
        await adapter.generate(request=grounded_request())
    await adapter.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, ResponseGenerationRequestError),
        (404, ResponseGenerationRequestError),
        (429, ResponseGenerationRateLimitError),
        (500, ResponseGenerationUnavailableError),
    ],
)
async def test_ollama_adapter_maps_http_failures_without_provider_details(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status_code, text="sensitive provider detail")

    adapter, _ = generator(httpx.MockTransport(handle))
    with pytest.raises(expected_error) as captured:
        await adapter.generate(request=grounded_request())
    assert "sensitive" not in str(captured.value)
    await adapter.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (
            httpx.ReadTimeout("sensitive timeout"),
            ResponseGenerationTimeoutError,
        ),
        (
            httpx.ConnectError("sensitive connection failure"),
            ResponseGenerationUnavailableError,
        ),
    ],
)
async def test_ollama_adapter_maps_transport_failures(
    provider_error: Exception,
    expected_error: type[Exception],
) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        del request
        raise provider_error

    adapter, _ = generator(httpx.MockTransport(handle))
    with pytest.raises(expected_error) as captured:
        await adapter.generate(request=grounded_request())
    assert "sensitive" not in str(captured.value)
    await adapter.close()


@pytest.mark.anyio
async def test_ollama_factory_applies_local_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_ollama_model="qwen3:8b",
        llm_ollama_base_url="http://127.0.0.1:11434",
        llm_request_timeout_seconds=12,
        llm_max_output_tokens=2048,
    )

    adapter = create_ollama_response_generator(settings)

    assert accepts_response_generator(adapter) is adapter
    await adapter.close()
