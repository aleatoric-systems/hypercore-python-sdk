#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Allow running directly via: python3 examples/feed_latency_examples.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hypercore_sdk import HyperCoreAPI, SDKConfig
from hypercore_sdk.example_auth import (
    disk_ws_key_candidates,
    grpc_key_candidates,
    load_env_credentials,
    mask_key,
    market_ws_key_candidates,
    pick_key,
    rpc_key_candidates,
    unified_key_candidates,
)
from hypercore_sdk.grpc_client import GrpcClient, GrpcConnectionConfig
from hypercore_sdk.stats import summarize_latencies
from hypercore_sdk.transport_diagnostics import classify_http_exception, summarize_event_availability
from hypercore_sdk.ws import get_price_from_ws


def _parse_ws_max_size(raw: str | None) -> int | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"", "none", "unlimited", "null", "0"}:
        return None
    size = int(normalized)
    if size <= 0:
        return None
    return size


def _retry_after_seconds(value: str | None, default_s: float = 1.0) -> float:
    if not value:
        return default_s
    try:
        parsed = float(value)
        if parsed > 0:
            return parsed
    except Exception:
        pass
    return default_s


def _iso_utc_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat(timespec="milliseconds")


def _attempt_start(attempt: int) -> dict[str, Any]:
    started_epoch_s = time.time()
    return {
        "attempt": attempt,
        "start_time_ms": int(started_epoch_s * 1000),
        "start_time_iso_utc": _iso_utc_from_epoch(started_epoch_s),
        "start_perf_counter_s": round(time.perf_counter(), 9),
    }


def _attempt_finish(
    base: dict[str, Any],
    *,
    ok: bool,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ended_epoch_s = time.time()
    end_perf = time.perf_counter()
    start_perf = float(base["start_perf_counter_s"])
    latency_ms = max(0.0, (end_perf - start_perf) * 1000.0)

    out = dict(base)
    out.update(
        {
            "end_time_ms": int(ended_epoch_s * 1000),
            "end_time_iso_utc": _iso_utc_from_epoch(ended_epoch_s),
            "end_perf_counter_s": round(end_perf, 9),
            "latency_ms": round(latency_ms, 3),
            "ok": ok,
        }
    )
    if error:
        out["error"] = error
    if metadata:
        out.update(metadata)
    return out


def _normalize_ts_ms(value: object) -> int | None:
    try:
        ts = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if ts <= 0:
        return None
    if ts < 1e11:
        return int(ts * 1000.0)
    if ts > 1e14:
        return int(ts / 1000.0)
    return int(ts)


def _extract_event_ts_ms(payload: object) -> int | None:
    stack: list[object] = [payload]
    visited = 0
    while stack and visited < 128:
        visited += 1
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("ts_ms", "timestamp_ms", "time_ms", "time", "timestamp", "ts", "t"):
                if key in node:
                    ts = _normalize_ts_ms(node.get(key))
                    if ts is not None:
                        return ts
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            for item in node[:8]:
                if isinstance(item, (dict, list)):
                    stack.append(item)
    return None


def _result_payload(events: list[dict[str, Any]], *, metric_kind: str) -> dict[str, Any]:
    latencies_ms = [float(evt["latency_ms"]) for evt in events if evt.get("ok")]
    errors = [str(evt.get("error")) for evt in events if not evt.get("ok") and evt.get("error")]
    event_ages_ms = [float(evt["event_age_ms"]) for evt in events if evt.get("ok") and evt.get("event_age_ms") is not None]
    return {
        "metric_kind": metric_kind,
        "stats": summarize_latencies(latencies_ms).as_dict(),
        "event_age_stats": summarize_latencies(event_ages_ms).as_dict(),
        "availability": summarize_event_availability(events),
        "ok": len(latencies_ms),
        "failed": len(errors),
        "errors": errors[:5],
        "events": events,
    }


def _http_get_latency(
    *,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout_s: float,
    verify_tls: bool,
    runs: int,
    min_interval_s: float,
    max_retry_429: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    next_allowed_at = 0.0
    with httpx.Client(timeout=timeout_s, verify=verify_tls) as client:
        for attempt in range(1, runs + 1):
            if min_interval_s > 0:
                now = time.perf_counter()
                if now < next_allowed_at:
                    time.sleep(next_allowed_at - now)
            evt = _attempt_start(attempt)
            try:
                response = client.get(url, headers=headers, params=params)
                retries = max(0, max_retry_429)
                while response.status_code == 429 and retries > 0:
                    retries -= 1
                    wait_s = _retry_after_seconds(response.headers.get("Retry-After"), default_s=min_interval_s or 1.0)
                    time.sleep(wait_s)
                    response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                events.append(_attempt_finish(evt, ok=True))
            except Exception as exc:  # pragma: no cover - network failures vary
                events.append(
                    _attempt_finish(
                        evt,
                        ok=False,
                        error=str(exc),
                        metadata=classify_http_exception(exc),
                    )
                )
            if min_interval_s > 0:
                next_allowed_at = time.perf_counter() + min_interval_s
    return _result_payload(events, metric_kind="request_response_rtt")


def _unified_sse_first_event_latency(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_s: float,
    verify_tls: bool,
    runs: int,
    min_interval_s: float,
    max_retry_429: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    url = f"{base_url.rstrip('/')}/api/v1/unified/stream"
    next_allowed_at = 0.0

    with httpx.Client(timeout=timeout_s, verify=verify_tls) as client:
        for attempt in range(1, runs + 1):
            if min_interval_s > 0:
                now = time.perf_counter()
                if now < next_allowed_at:
                    time.sleep(next_allowed_at - now)
            evt = _attempt_start(attempt)
            try:
                retries = max(0, max_retry_429)
                while True:
                    with client.stream("GET", url, headers=headers) as response:
                        if response.status_code == 429 and retries > 0:
                            retries -= 1
                            wait_s = _retry_after_seconds(response.headers.get("Retry-After"), default_s=min_interval_s or 1.0)
                            time.sleep(wait_s)
                            continue
                        response.raise_for_status()
                        found = False
                        for raw_line in response.iter_lines():
                            line = raw_line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            body = line[5:].strip()
                            if not body:
                                continue
                            event_ts_ms: int | None = None
                            try:
                                parsed = json.loads(body)
                                event_ts_ms = _extract_event_ts_ms(parsed)
                            except Exception:
                                parsed = None
                            done = _attempt_finish(evt, ok=True)
                            done["sse_payload_parsed"] = parsed is not None
                            if event_ts_ms is not None:
                                now_ms = int(time.time() * 1000)
                                done["event_ts_ms"] = event_ts_ms
                                done["event_age_ms"] = max(0, now_ms - event_ts_ms)
                            events.append(done)
                            found = True
                            break
                        if not found:
                            raise RuntimeError("No SSE data events received from unified stream")
                    break
            except Exception as exc:  # pragma: no cover - network failures vary
                events.append(
                    _attempt_finish(
                        evt,
                        ok=False,
                        error=str(exc),
                        metadata=classify_http_exception(exc),
                    )
                )
            if min_interval_s > 0:
                next_allowed_at = time.perf_counter() + min_interval_s

    return _result_payload(events, metric_kind="time_to_first_event")


async def _disk_ws_first_event(
    *,
    ws_url: str,
    timeout_s: float,
    api_key: str | None,
    max_message_bytes: int | None,
) -> dict[str, Any]:
    import websockets

    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    start = time.perf_counter()
    async with websockets.connect(
        ws_url,
        additional_headers=headers,
        max_size=max_message_bytes,
    ) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
        latency_ms = (time.perf_counter() - start) * 1000.0
        payload: Any
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": str(raw)}
        return {
            "latency_ms": round(latency_ms, 3),
            "payload": payload,
        }


def _disk_ws_first_event_latency(
    *,
    ws_url: str,
    timeout_s: float,
    api_key: str | None,
    runs: int,
    max_message_bytes: int | None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
        try:
            result = asyncio.run(
                _disk_ws_first_event(
                    ws_url=ws_url,
                    timeout_s=timeout_s,
                    api_key=api_key,
                    max_message_bytes=max_message_bytes,
                )
            )
            done = _attempt_finish(evt, ok=True)
            payload = result.get("payload")
            event_ts_ms: int | None = None
            if isinstance(payload, dict):
                ingest_ts_us = payload.get("ingest_ts_us")
                if ingest_ts_us is not None:
                    try:
                        event_ts_ms = int(float(ingest_ts_us) / 1000.0)
                    except Exception:
                        event_ts_ms = None
                if event_ts_ms is None:
                    event_ts_ms = _extract_event_ts_ms(payload)
            if event_ts_ms is not None:
                now_ms = int(time.time() * 1000)
                done["event_ts_ms"] = event_ts_ms
                done["event_age_ms"] = max(0, now_ms - event_ts_ms)
            events.append(done)
        except Exception as exc:  # pragma: no cover - network failures vary
            events.append(_attempt_finish(evt, ok=False, error=str(exc)))

    return _result_payload(events, metric_kind="time_to_first_event")


def _grpc_stream_first_event_latency(
    *,
    grpc_client: GrpcClient,
    coin: str,
    subscription: str,
    heartbeat_s: int,
    runs: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
        try:
            messages = grpc_client.stream_mids(
                coin=coin,
                subscription=subscription,
                heartbeat_s=heartbeat_s,
                max_messages=1,
            )
            if not messages:
                raise RuntimeError(f"No messages for subscription={subscription!r}")
            first = messages[0]
            done = _attempt_finish(evt, ok=True)
            done["stream_channel"] = first.get("channel")
            done["stream_source"] = first.get("source")
            event_ts_ms = _normalize_ts_ms(first.get("ts_ms"))
            if event_ts_ms is not None:
                now_ms = int(time.time() * 1000)
                done["event_ts_ms"] = event_ts_ms
                done["event_age_ms"] = max(0, now_ms - event_ts_ms)
            events.append(done)
        except Exception as exc:  # pragma: no cover - network failures vary
            events.append(_attempt_finish(evt, ok=False, error=str(exc)))

    return _result_payload(events, metric_kind="time_to_first_event")


def _grpc_liquidations_first_event_latency(
    *,
    grpc_client: GrpcClient,
    coin: str,
    heartbeat_s: int,
    runs: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    skipped_reason = "liquidation topics are not configured"

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
        try:
            messages = grpc_client.stream_liquidations(
                coin=coin,
                heartbeat_s=heartbeat_s,
                max_messages=1,
            )
            if not messages:
                raise RuntimeError("No liquidation events received")
            first = messages[0]
            done = _attempt_finish(evt, ok=True)
            done["stream_channel"] = first.get("channel")
            done["stream_source"] = first.get("source")
            done["tx_hash"] = first.get("tx_hash")
            done["block_number"] = first.get("block_number")
            event_ts_ms = _normalize_ts_ms(first.get("ts_ms"))
            if event_ts_ms is not None:
                now_ms = int(time.time() * 1000)
                done["event_ts_ms"] = event_ts_ms
                done["event_age_ms"] = max(0, now_ms - event_ts_ms)
            events.append(done)
        except Exception as exc:  # pragma: no cover - network failures vary
            msg = str(exc)
            done = _attempt_finish(evt, ok=False, error=msg)
            if skipped_reason in msg.lower():
                done["skipped"] = True
            events.append(done)

    if events and all(evt.get("skipped") for evt in events):
        return {
            "metric_kind": "time_to_first_event",
            "stats": summarize_latencies([]).as_dict(),
            "event_age_stats": summarize_latencies([]).as_dict(),
            "ok": 0,
            "failed": 0,
            "skipped": len(events),
            "errors": [f"skipped: {skipped_reason}"],
            "events": events,
            "skipped_reason": skipped_reason,
        }

    return _result_payload(events, metric_kind="time_to_first_event")


def _rpc_block_latency(*, api: HyperCoreAPI, runs: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
        try:
            api.block_number()
            events.append(_attempt_finish(evt, ok=True))
        except Exception as exc:  # pragma: no cover - network failures vary
            events.append(
                _attempt_finish(
                    evt,
                    ok=False,
                    error=str(exc),
                    metadata=classify_http_exception(exc),
                )
            )

    return _result_payload(events, metric_kind="request_response_rtt")


def _ws_first_event_latency(
    *,
    ws_url: str,
    coin: str,
    subscription_type: str,
    timeout_s: float,
    api_key: str | None,
    runs: int,
    max_message_bytes: int | None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
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
            done = _attempt_finish(evt, ok=True)
            done["stream_channel"] = result.get("channel")
            done["sdk_reported_latency_ms"] = result.get("latency_ms")
            raw_msg = result.get("message")
            event_ts_ms = _extract_event_ts_ms(raw_msg)
            if event_ts_ms is not None:
                now_ms = int(time.time() * 1000)
                done["event_ts_ms"] = event_ts_ms
                done["event_age_ms"] = max(0, now_ms - event_ts_ms)
            events.append(done)
        except Exception as exc:  # pragma: no cover - network failures vary
            events.append(_attempt_finish(evt, ok=False, error=str(exc)))

    return _result_payload(events, metric_kind="time_to_first_event")


def _grpc_health_latency(*, grpc_client: GrpcClient, runs: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    for attempt in range(1, runs + 1):
        evt = _attempt_start(attempt)
        try:
            grpc_client.health_check(service="")
            events.append(_attempt_finish(evt, ok=True))
        except Exception as exc:  # pragma: no cover - network failures vary
            events.append(_attempt_finish(evt, ok=False, error=str(exc)))

    return _result_payload(events, metric_kind="request_response_rtt")


def _feed_type(feed_name: str) -> str:
    return feed_name.split(".", 1)[0]


def _profile_label(p95_ms: float) -> str:
    if p95_ms <= 50:
        return "very_low"
    if p95_ms <= 200:
        return "low"
    if p95_ms <= 1000:
        return "moderate"
    if p95_ms <= 3000:
        return "elevated"
    return "high"


def _build_feed_type_summary(feeds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for feed_name, feed_result in feeds.items():
        group = _feed_type(feed_name)
        bucket = grouped.setdefault(group, {"feeds": [], "latencies_ms": [], "ok": 0, "failed": 0})
        bucket["feeds"].append(feed_name)
        bucket["ok"] += int(feed_result.get("ok", 0))
        bucket["failed"] += int(feed_result.get("failed", 0))

        for evt in feed_result.get("events", []):
            if isinstance(evt, dict) and evt.get("ok") and "latency_ms" in evt:
                bucket["latencies_ms"].append(float(evt["latency_ms"]))

    summary: dict[str, Any] = {}
    for group, bucket in grouped.items():
        ok = int(bucket["ok"])
        failed = int(bucket["failed"])
        total = ok + failed
        stats = summarize_latencies(list(bucket["latencies_ms"])).as_dict()
        p95 = float(stats.get("p95_ms", 0.0))
        summary[group] = {
            "feeds": bucket["feeds"],
            "samples": {
                "ok": ok,
                "failed": failed,
                "total": total,
                "success_rate_pct": round((ok / total) * 100.0, 2) if total else 0.0,
            },
            "aggregate_stats": stats,
            "latency_profile": _profile_label(p95) if ok else "no_successful_samples",
            "overview": (
                f"{group}: p50={stats['p50_ms']} ms, p95={stats['p95_ms']} ms, "
                f"success={round((ok / total) * 100.0, 2) if total else 0.0}%"
                if total
                else f"{group}: no samples"
            ),
        }
    return summary


def _build_metric_kind_summary(feeds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for feed_name, feed_result in feeds.items():
        metric_kind = str(feed_result.get("metric_kind", "unknown"))
        bucket = grouped.setdefault(metric_kind, {"feeds": [], "latencies_ms": [], "event_ages_ms": [], "ok": 0, "failed": 0})
        bucket["feeds"].append(feed_name)
        bucket["ok"] += int(feed_result.get("ok", 0))
        bucket["failed"] += int(feed_result.get("failed", 0))

        for evt in feed_result.get("events", []):
            if not isinstance(evt, dict) or not evt.get("ok"):
                continue
            if "latency_ms" in evt:
                bucket["latencies_ms"].append(float(evt["latency_ms"]))
            if evt.get("event_age_ms") is not None:
                bucket["event_ages_ms"].append(float(evt["event_age_ms"]))

    summary: dict[str, Any] = {}
    for metric_kind, bucket in grouped.items():
        ok = int(bucket["ok"])
        failed = int(bucket["failed"])
        total = ok + failed
        stats = summarize_latencies(list(bucket["latencies_ms"])).as_dict()
        age_stats = summarize_latencies(list(bucket["event_ages_ms"])).as_dict()
        summary[metric_kind] = {
            "feeds": bucket["feeds"],
            "samples": {
                "ok": ok,
                "failed": failed,
                "total": total,
                "success_rate_pct": round((ok / total) * 100.0, 2) if total else 0.0,
            },
            "latency_stats": stats,
            "event_age_stats": age_stats,
            "overview": (
                f"{metric_kind}: p50={stats['p50_ms']} ms, p95={stats['p95_ms']} ms, "
                f"event_age_p50={age_stats['p50_ms']} ms"
            ),
        }
    return summary


def _build_availability_alerts(feeds: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for feed_name, feed_result in feeds.items():
        availability = feed_result.get("availability")
        if not isinstance(availability, dict):
            continue
        state = str(availability.get("state", "unknown"))
        if state in {"ok", "unknown"}:
            continue
        alerts.append(
            {
                "feed": feed_name,
                "state": state,
                "reason": availability.get("reason"),
                "error_kinds": availability.get("error_kinds", []),
                "status_codes": availability.get("status_codes", []),
            }
        )
    return alerts


def build_parser() -> argparse.ArgumentParser:
    load_env_credentials(PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark available Hypercore feeds and report latency stats. "
            "Includes RPC, WS channels, gRPC health, gRPC stream subscriptions, and unified endpoints."
        )
    )

    default_cfg = SDKConfig()
    parser.add_argument("--coin", default="BTC", help="Asset symbol for feed tests.")
    parser.add_argument("--runs", type=int, default=5, help="Number of attempts per feed.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds per call.")

    parser.add_argument("--rpc-url", default=os.getenv("ALEATORIC_RPC_URL", default_cfg.rpc_url))
    parser.add_argument(
        "--ws-url",
        default=os.getenv("ALEATORIC_MARKET_WS_URL") or os.getenv("HYPER_MARKET_WS_URL", "wss://api.hyperliquid.xyz/ws"),
        help="Market WS endpoint for allMids/trades/l2Book subscriptions.",
    )
    parser.add_argument(
        "--disk-ws-url",
        default=os.getenv("ALEATORIC_DISK_WS_URL", default_cfg.ws_url),
        help="Disk-sync WS endpoint for replica_cmd stream.",
    )
    parser.add_argument("--stream-url", default=os.getenv("ALEATORIC_STREAM_URL", default_cfg.unified_stream_url))
    parser.add_argument("--grpc-target", default=os.getenv("ALEATORIC_GRPC_TARGET", default_cfg.grpc_target), help="host:port")
    parser.add_argument("--grpc-server-name", default=os.getenv("ALEATORIC_GRPC_SERVER_NAME", default_cfg.grpc_server_name))
    parser.add_argument("--grpc-plaintext", action="store_true", default=False, help="Disable TLS for gRPC.")
    parser.add_argument("--grpc-heartbeat-s", type=int, default=10)
    parser.add_argument(
        "--grpc-subscriptions",
        default="allMids,trades,l2Book",
        help="Comma-separated gRPC StreamMids subscriptions to benchmark.",
    )
    parser.add_argument(
        "--grpc-include-liquidations",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("HYPER_GRPC_INCLUDE_LIQUIDATIONS", "false").lower() in {"1", "true", "yes", "on"},
        help="Also benchmark the dedicated PriceService/StreamLiquidations endpoint.",
    )
    parser.add_argument(
        "--grpc-liquidations-heartbeat-s",
        type=int,
        default=int(os.getenv("HYPER_GRPC_LIQ_HEARTBEAT_S", "1")),
        help="Heartbeat interval for StreamLiquidations benchmark.",
    )

    parser.add_argument("--api-key", default=None)
    parser.add_argument("--rpc-key", default=None)
    parser.add_argument("--grpc-key", default=None)
    parser.add_argument("--ws-key", default=None)
    parser.add_argument("--disk-ws-key", default=None)
    parser.add_argument("--unified-key", default=None)
    parser.add_argument(
        "--ws-max-size",
        default=os.getenv("HYPER_WS_MAX_SIZE", "none"),
        help="Max WS frame size in bytes. Use 'none' to disable limit (recommended for disk feed).",
    )
    parser.add_argument(
        "--unified-min-interval-ms",
        type=float,
        default=float(os.getenv("HYPER_UNIFIED_MIN_INTERVAL_MS", "700")),
        help="Minimum delay between unified requests to reduce 429s.",
    )
    parser.add_argument(
        "--unified-retry-429",
        type=int,
        default=int(os.getenv("HYPER_UNIFIED_RETRY_429", "1")),
        help="Retry count per unified request when 429 is returned.",
    )
    parser.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=default_cfg.verify_tls,
        help="Verify TLS certificates (enabled by default).",
    )

    parser.add_argument("--skip-rpc", action="store_true", default=False)
    parser.add_argument("--skip-ws", action="store_true", default=False)
    parser.add_argument("--skip-disk-ws", action="store_true", default=False)
    parser.add_argument("--skip-grpc", action="store_true", default=False)
    parser.add_argument("--skip-unified", action="store_true", default=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ws_max_size = _parse_ws_max_size(args.ws_max_size)
    rpc_resolution = pick_key(args.rpc_key, [("api_key", args.api_key), *rpc_key_candidates()])
    rpc_key = rpc_resolution.value
    grpc_resolution = pick_key(args.grpc_key, [("api_key", args.api_key), *grpc_key_candidates()])
    grpc_key = grpc_resolution.value
    ws_resolution = pick_key(args.ws_key, [("api_key", args.api_key), *market_ws_key_candidates()])
    ws_key = ws_resolution.value
    disk_ws_resolution = pick_key(args.disk_ws_key, [("unified_key", args.unified_key), *disk_ws_key_candidates()])
    disk_ws_key = disk_ws_resolution.value
    unified_resolution = pick_key(
        args.unified_key,
        [("disk_ws_key", disk_ws_key), ("api_key", args.api_key), *unified_key_candidates()],
    )
    unified_key = unified_resolution.value

    cfg = SDKConfig(
        rpc_url=args.rpc_url,
        ws_url=args.ws_url,
        info_url=SDKConfig().info_url,
        unified_stream_url=args.stream_url,
        grpc_target=args.grpc_target,
        api_key=rpc_key,
        timeout_s=args.timeout,
        verify_tls=args.verify_tls,
        grpc_tls=not args.grpc_plaintext,
        grpc_server_name=args.grpc_server_name,
    )

    output: dict[str, Any] = {
        "coin": args.coin,
        "runs": args.runs,
        "timeout_s": args.timeout,
        "measurement_notes": {
            "request_response_rtt": "Full request/response latency measured with local monotonic clock.",
            "time_to_first_event": "Connect+subscribe until first qualifying stream event is received.",
            "event_age_ms": "Approximate freshness at receipt: now_ms - event_ts_ms (clock skew can affect this).",
        },
        "auth_key_selection": {
            "rpc_key": mask_key(rpc_key),
            "grpc_key": mask_key(grpc_key),
            "ws_key": mask_key(ws_key),
            "disk_ws_key": mask_key(disk_ws_key),
            "unified_key": mask_key(unified_key),
        },
        "auth_key_sources": {
            "rpc_key": rpc_resolution.source,
            "grpc_key": grpc_resolution.source,
            "ws_key": ws_resolution.source,
            "disk_ws_key": disk_ws_resolution.source,
            "unified_key": unified_resolution.source,
        },
        "latency_measurement_stamps": {
            "start_time_ms": "unix epoch milliseconds (wall clock)",
            "start_time_iso_utc": "ISO-8601 UTC wall-clock timestamp",
            "start_perf_counter_s": "local monotonic perf counter at attempt start",
            "latency_ms": "derived from (end_perf_counter_s - start_perf_counter_s) * 1000",
        },
        "feeds": {},
    }

    if not args.skip_rpc:
        with HyperCoreAPI(cfg) as api:
            output["feeds"]["rpc.eth_blockNumber"] = _rpc_block_latency(api=api, runs=args.runs)

    if not args.skip_ws:
        output["feeds"]["ws.allMids"] = _ws_first_event_latency(
            ws_url=args.ws_url,
            coin=args.coin,
            subscription_type="allMids",
            timeout_s=args.timeout,
            api_key=ws_key,
            runs=args.runs,
            max_message_bytes=ws_max_size,
        )
        output["feeds"]["ws.trades"] = _ws_first_event_latency(
            ws_url=args.ws_url,
            coin=args.coin,
            subscription_type="trades",
            timeout_s=args.timeout,
            api_key=ws_key,
            runs=args.runs,
            max_message_bytes=ws_max_size,
        )
        output["feeds"]["ws.l2Book"] = _ws_first_event_latency(
            ws_url=args.ws_url,
            coin=args.coin,
            subscription_type="l2Book",
            timeout_s=args.timeout,
            api_key=ws_key,
            runs=args.runs,
            max_message_bytes=ws_max_size,
        )

    if not args.skip_disk_ws and args.disk_ws_url:
        output["feeds"]["disk.replica_cmd"] = _disk_ws_first_event_latency(
            ws_url=args.disk_ws_url,
            timeout_s=args.timeout,
            api_key=disk_ws_key,
            runs=args.runs,
            max_message_bytes=ws_max_size,
        )

    if not args.skip_grpc:
        grpc_cfg = GrpcConnectionConfig(
            target=args.grpc_target,
            timeout_s=args.timeout,
            use_tls=not args.grpc_plaintext,
            server_name=args.grpc_server_name,
            api_key=grpc_key,
        )
        grpc_client = GrpcClient(grpc_cfg)
        output["feeds"]["grpc.health"] = _grpc_health_latency(grpc_client=grpc_client, runs=args.runs)

        subscriptions = [item.strip() for item in args.grpc_subscriptions.split(",") if item.strip()]
        wants_liquidations = args.grpc_include_liquidations
        mids_subscriptions: list[str] = []
        for subscription in subscriptions:
            if subscription.lower() == "liquidations":
                wants_liquidations = True
                continue
            mids_subscriptions.append(subscription)

        for subscription in mids_subscriptions:
            output["feeds"][f"grpc.stream:{subscription}"] = _grpc_stream_first_event_latency(
                grpc_client=grpc_client,
                coin=args.coin,
                subscription=subscription,
                heartbeat_s=args.grpc_heartbeat_s,
                runs=args.runs,
            )

        if wants_liquidations:
            output["feeds"]["grpc.liquidations"] = _grpc_liquidations_first_event_latency(
                grpc_client=grpc_client,
                coin=args.coin,
                heartbeat_s=args.grpc_liquidations_heartbeat_s,
                runs=args.runs,
            )

    if not args.skip_unified:
        headers: dict[str, str] = {"accept": "application/json"}
        if unified_key:
            headers["x-api-key"] = unified_key

        base_url = args.stream_url.rstrip("/")
        output["feeds"]["unified.stats"] = _http_get_latency(
            url=f"{base_url}/api/v1/unified/stats",
            headers=headers,
            params=None,
            timeout_s=args.timeout,
            verify_tls=args.verify_tls,
            runs=args.runs,
            min_interval_s=max(0.0, args.unified_min_interval_ms / 1000.0),
            max_retry_429=args.unified_retry_429,
        )
        output["feeds"]["unified.events"] = _http_get_latency(
            url=f"{base_url}/api/v1/unified/events",
            headers=headers,
            params={"limit": 1},
            timeout_s=args.timeout,
            verify_tls=args.verify_tls,
            runs=args.runs,
            min_interval_s=max(0.0, args.unified_min_interval_ms / 1000.0),
            max_retry_429=args.unified_retry_429,
        )
        output["feeds"]["unified.sse_first_event"] = _unified_sse_first_event_latency(
            base_url=base_url,
            headers=headers,
            timeout_s=args.timeout,
            verify_tls=args.verify_tls,
            runs=args.runs,
            min_interval_s=max(0.0, args.unified_min_interval_ms / 1000.0),
            max_retry_429=args.unified_retry_429,
        )

    output["summary_by_feed_type"] = _build_feed_type_summary(output["feeds"])
    output["summary_by_metric_kind"] = _build_metric_kind_summary(output["feeds"])
    output["availability_alerts"] = _build_availability_alerts(output["feeds"])
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
