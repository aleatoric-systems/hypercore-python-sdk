from __future__ import annotations

from typing import Any, Literal

import httpx

from .config import SDKConfig


class StatusClient:
    """Client for Hypernode status API surfaces."""

    def __init__(self, config: SDKConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.config.timeout_s,
            verify=self.config.verify_tls,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "StatusClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        self.close()
        return False

    def _headers(self, *, bearer: str | None = None) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if bearer:
            headers["authorization"] = f"Bearer {bearer}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.status_url.rstrip('/')}{path}"

    def _get_json(self, path: str, *, bearer: str | None = None, label: str) -> dict[str, Any]:
        response = self._client.get(self._url(path), headers=self._headers(bearer=bearer))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected {label} payload: {payload!r}")
        return payload

    def health(self) -> dict[str, Any]:
        return self._get_json("/healthz", label="status health")

    def public_status(self) -> dict[str, Any]:
        return self._get_json("/api/v1/public/status", label="public status")

    def private_status(self) -> dict[str, Any]:
        return self._get_json("/api/v1/status", bearer=self.config.status_token, label="private status")

    def admin_tokens(self) -> dict[str, Any]:
        return self._get_json("/api/v1/admin/tokens", bearer=self.config.status_token, label="admin tokens")
