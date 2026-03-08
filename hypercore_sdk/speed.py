from __future__ import annotations

import asyncio
import time
from typing import Any

from .api import HyperCoreAPI
from .grpc_client import GrpcClient
from .stats import summarize_latencies
from .ws import get_price_from_ws


def run_rpc_speed_test(api: HyperCoreAPI, *, count: int = 30) -> dict[str, Any]:
    latencies: list[float] = []
    errors: list[str] = []
    for _ in range(count):
        start = time.perf_counter()
        try:
            api.block_number()
            latencies.append((time.perf_counter() - start) * 1000.0)
        except Exception as exc:  # pragma: no cover - network failures vary
            errors.append(str(exc))
    return {
        "stats": summarize_latencies(latencies).as_dict(),
        "ok": len(latencies),
        "failed": len(errors),
        "errors": errors[:5],
    }


def run_ws_speed_test(
    *,
    ws_url: str,
    coin: str = "BTC",
    subscription_type: str = "allMids",
    count: int = 10,
    timeout_s: float = 10.0,
    api_key: str | None = None,
    max_message_bytes: int | None = None,
) -> dict[str, Any]:
    latencies: list[float] = []
    errors: list[str] = []
    for _ in range(count):
        try:
            result = asyncio.run(
                get_price_from_ws(
                    ws_url=ws_url,
                    coin=coin,
                    subscription_type=subscription_type,
                    timeout_s=timeout_s,
                    api_key=api_key,
                    max_message_bytes=max_message_bytes,
                )
            )
            latencies.append(float(result["latency_ms"]))
        except Exception as exc:  # pragma: no cover - network failures vary
            errors.append(str(exc))
    return {
        "stats": summarize_latencies(latencies).as_dict(),
        "ok": len(latencies),
        "failed": len(errors),
        "errors": errors[:5],
    }


def run_grpc_health_speed_test(grpc_client: GrpcClient, *, count: int = 20, service: str = "") -> dict[str, Any]:
    return grpc_client.health_speed_test(count=count, service=service)
