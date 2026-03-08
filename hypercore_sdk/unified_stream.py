from __future__ import annotations

import json
from typing import Any, Generator, Literal

import httpx

from .config import SDKConfig


class UnifiedStreamClient:
    """Client for Aleatoric dedicated unified event stream endpoints."""

    def __init__(self, config: SDKConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.config.timeout_s,
            verify=self.config.verify_tls,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "UnifiedStreamClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        self.close()
        return False

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"accept": "application/json"}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.unified_stream_url.rstrip('/')}{path}"

    def stats(self) -> dict[str, Any]:
        response = self._client.get(self._url("/api/v1/unified/stats"), headers=self._auth_headers())
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected stats payload: {payload!r}")
        return payload

    def events(self, limit: int = 200) -> dict[str, Any]:
        response = self._client.get(
            self._url("/api/v1/unified/events"),
            headers=self._auth_headers(),
            params={"limit": max(1, int(limit))},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected events payload: {payload!r}")
        return payload

    def sse_events(self, max_events: int = 20) -> Generator[dict[str, Any], None, None]:
        target = max(1, int(max_events))
        seen = 0
        with self._client.stream("GET", self._url("/api/v1/unified/stream"), headers=self._auth_headers()) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body:
                    continue
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    yield parsed
                    seen += 1
                    if seen >= target:
                        return
