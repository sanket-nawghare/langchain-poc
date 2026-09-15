"""Local observability and defensive HTTP middleware."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("clinical_workflow.http")


@dataclass
class MetricsRegistry:
    """Small process-local metrics registry for the local MVP."""

    request_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    route_counts: dict[str, int] = field(default_factory=dict)
    total_latency_ms: int = 0
    max_latency_ms: int = 0
    rate_limited_count: int = 0
    body_rejected_count: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_http_request(
        self,
        *,
        path: str,
        status_code: int,
        latency_ms: int,
    ) -> None:
        """Record one completed HTTP request without payload details."""

        status_class = f"{status_code // 100}xx"
        with self._lock:
            self.request_count += 1
            self.status_counts[status_class] = (
                self.status_counts.get(status_class, 0) + 1
            )
            self.route_counts[path] = self.route_counts.get(path, 0) + 1
            self.total_latency_ms += latency_ms
            self.max_latency_ms = max(self.max_latency_ms, latency_ms)

    def record_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited_count += 1

    def record_body_rejected(self) -> None:
        with self._lock:
            self.body_rejected_count += 1

    def snapshot(self) -> dict[str, object]:
        """Return an operator-readable metrics snapshot."""

        with self._lock:
            average_latency_ms = (
                round(self.total_latency_ms / self.request_count)
                if self.request_count
                else 0
            )
            return {
                "request_count": self.request_count,
                "status_counts": dict(sorted(self.status_counts.items())),
                "route_counts": dict(sorted(self.route_counts.items())),
                "average_latency_ms": average_latency_ms,
                "max_latency_ms": self.max_latency_ms,
                "rate_limited_count": self.rate_limited_count,
                "body_rejected_count": self.body_rejected_count,
            }


metrics_registry = MetricsRegistry()


class SecurityHeadersMiddleware:
    """Attach conservative browser and API hardening headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Permissions-Policy", "geolocation=()")
                headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'none'; frame-ancestors 'none'",
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestBodyLimitMiddleware:
    """Reject oversized requests before endpoint validation."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                body_bytes = int(content_length)
            except ValueError:
                body_bytes = self.max_body_bytes + 1
            if body_bytes > self.max_body_bytes:
                metrics_registry.record_body_rejected()
                response = JSONResponse(
                    status_code=413,
                    content={
                        "request_id": str(uuid4()),
                        "error": {
                            "code": "request_body_too_large",
                            "message": "The request body is too large.",
                        },
                    },
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


class WorkflowRateLimitMiddleware:
    """Apply a small in-process fixed-window limit to workflow submissions."""

    def __init__(self, app: ASGIApp, *, requests_per_minute: int) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._applies(scope):
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        key = self._client_key(scope)
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and now - timestamps[0] >= 60:
                timestamps.popleft()
            if len(timestamps) >= self.requests_per_minute:
                metrics_registry.record_rate_limited()
                response = JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                    content={
                        "request_id": str(uuid4()),
                        "error": {
                            "code": "rate_limited",
                            "message": "Too many workflow requests. Retry later.",
                        },
                    },
                )
                await response(scope, receive, send)
                return
            timestamps.append(now)

        await self.app(scope, receive, send)

    @staticmethod
    def _applies(scope: Scope) -> bool:
        return (
            str(scope["method"]) == "POST" and str(scope["path"]) == "/api/v1/workflows"
        )

    @staticmethod
    def _client_key(scope: Scope) -> str:
        client = scope.get("client")
        host = client[0] if client else "unknown"
        return f"{host}:workflow-post"


class RequestObservabilityMiddleware:
    """Emit structured request logs and process-local metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            path = str(scope["path"])
            metrics_registry.record_http_request(
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
            )
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": path,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                    },
                    sort_keys=True,
                )
            )
