from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class SDKConfig:
    rpc_url: str = os.getenv("HYPER_RPC_URL", "https://rpc.aleatoric.systems/")
    ws_url: str = os.getenv("HYPER_WS_URL", "wss://disk.grpc.aleatoric.systems/")
    info_url: str = os.getenv("HYPER_INFO_URL", "https://api.hyperliquid.xyz/info")
    unified_stream_url: str = os.getenv("HYPER_UNIFIED_STREAM_URL", "https://unified.grpc.aleatoric.systems")
    status_url: str = os.getenv("HYPER_STATUS_URL", "http://127.0.0.1:8090")
    grpc_target: str = os.getenv("HYPER_GRPC_TARGET", "hl.grpc.aleatoric.systems:443")
    api_key: str | None = os.getenv("HYPER_API_KEY")
    unified_stream_api_key: str | None = os.getenv("UNIFIED_STREAM_KEY") or os.getenv("HYPER_UNIFIED_STREAM_API_KEY")
    grpc_api_key: str | None = os.getenv("ALEATORIC_GRPC_KEY") or os.getenv("HYPER_GRPC_API_KEY")
    status_token: str | None = os.getenv("HYPER_STATUS_TOKEN")
    timeout_s: float = float(os.getenv("HYPER_TIMEOUT_S", "10"))
    verify_tls: bool = _env_bool("HYPER_VERIFY_TLS", True)
    grpc_tls: bool = _env_bool("HYPER_GRPC_TLS", True)
    grpc_server_name: str | None = os.getenv("HYPER_GRPC_SERVER_NAME")

    def auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers
