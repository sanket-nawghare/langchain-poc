"""Loopback-only asynchronous Weaviate connection for local retrieval."""

from urllib.parse import urlsplit

import weaviate
from weaviate import WeaviateAsyncClient
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.exceptions import WeaviateBaseError, WeaviateTimeoutError

from app.core.config import Settings
from app.rag.vector_store import (
    GuidelineVectorStoreSchemaError,
    GuidelineVectorStoreTimeoutError,
    GuidelineVectorStoreUnavailableError,
)


async def connect_local_async_weaviate(settings: Settings) -> WeaviateAsyncClient:
    """Connect to an explicitly loopback-only HTTP/gRPC Weaviate endpoint."""

    parsed = urlsplit(str(settings.weaviate_url))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise GuidelineVectorStoreSchemaError(
            "local guideline retrieval requires a loopback-only HTTP Weaviate URL"
        )
    if parsed.hostname is None:
        raise GuidelineVectorStoreSchemaError("local Weaviate URL has no host")

    client = weaviate.use_async_with_custom(
        http_host=parsed.hostname,
        http_port=parsed.port or 80,
        http_secure=False,
        grpc_host=parsed.hostname,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=False,
        additional_config=AdditionalConfig(
            timeout=Timeout(
                init=settings.dependency_timeout_seconds,
                query=settings.weaviate_request_timeout_seconds,
                insert=settings.weaviate_request_timeout_seconds,
            )
        ),
    )
    try:
        await client.connect()
    except WeaviateTimeoutError as error:
        await client.close()
        raise GuidelineVectorStoreTimeoutError(
            "local Weaviate connection timed out"
        ) from error
    except WeaviateBaseError as error:
        await client.close()
        raise GuidelineVectorStoreUnavailableError(
            "local Weaviate connection is unavailable"
        ) from error
    return client
