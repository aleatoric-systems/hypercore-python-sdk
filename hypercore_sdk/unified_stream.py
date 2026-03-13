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
        api_key = self.config.unified_stream_api_key or self.config.api_key
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.unified_stream_url.rstrip('/')}{path}"

    @staticmethod
    def _query_params(**kwargs: Any) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is None:
                continue
            if isinstance(value, str) and not value:
                continue
            params[key] = value
        return params

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None, label: str) -> dict[str, Any]:
        response = self._client.get(self._url(path), headers=self._auth_headers(), params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected {label} payload: {payload!r}")
        return payload

    def stats(self) -> dict[str, Any]:
        return self._get_json("/api/v1/unified/stats", label="stats")

    def events(self, limit: int = 200, *, event_type: str | None = None, stream: str | None = None) -> dict[str, Any]:
        params = self._query_params(limit=max(1, int(limit)), event_type=event_type, stream=stream)
        return self._get_json("/api/v1/unified/events", params=params, label="events")

    def consensus_pulse(self) -> dict[str, Any]:
        return self._get_json("/api/v1/unified/consensus-pulse", label="consensus pulse")

    def all_mids(self, *, dex: str = "") -> dict[str, Any]:
        params = self._query_params(dex=dex)
        return self._get_json("/api/v1/unified/all-mids", params=params, label="all-mids")

    def l2_book(self, coin: str, *, dex: str = "", depth: int | None = None) -> dict[str, Any]:
        params = self._query_params(coin=coin, dex=dex, depth=max(1, int(depth)) if depth is not None else None)
        return self._get_json("/api/v1/unified/l2-book", params=params, label="l2-book")

    def asset_contexts(self, *, coin: str | None = None, dex: str = "") -> dict[str, Any]:
        params = self._query_params(coin=coin, dex=dex)
        return self._get_json("/api/v1/unified/asset-contexts", params=params, label="asset-contexts")

    def _sse_objects(self, path: str, *, params: dict[str, Any] | None = None, max_events: int = 20) -> Generator[dict[str, Any], None, None]:
        target = max(1, int(max_events))
        seen = 0
        with self._client.stream("GET", self._url(path), headers=self._auth_headers(), params=params) as response:
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

    def sse_events(self, max_events: int = 20) -> Generator[dict[str, Any], None, None]:
        yield from self._sse_objects("/api/v1/unified/stream", max_events=max_events)

    def sse_all_mids(self, *, dex: str = "", max_events: int = 20) -> Generator[dict[str, Any], None, None]:
        params = self._query_params(dex=dex)
        yield from self._sse_objects("/api/v1/unified/all-mids/stream", params=params, max_events=max_events)

    def sse_l2_book(
        self,
        coin: str,
        *,
        dex: str = "",
        depth: int | None = None,
        max_events: int = 20,
    ) -> Generator[dict[str, Any], None, None]:
        params = self._query_params(coin=coin, dex=dex, depth=max(1, int(depth)) if depth is not None else None)
        yield from self._sse_objects("/api/v1/unified/l2-book/stream", params=params, max_events=max_events)

    def sse_asset_contexts(
        self,
        *,
        coin: str | None = None,
        dex: str = "",
        max_events: int = 20,
    ) -> Generator[dict[str, Any], None, None]:
        params = self._query_params(coin=coin, dex=dex)
        yield from self._sse_objects("/api/v1/unified/asset-contexts/stream", params=params, max_events=max_events)
