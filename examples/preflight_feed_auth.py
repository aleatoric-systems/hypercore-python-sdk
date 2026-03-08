#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import httpx
from websockets.sync.client import connect as ws_connect

# Allow running directly via: python3 examples/preflight_feed_auth.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hypercore_sdk import SDKConfig
from hypercore_sdk.grpc_client import GrpcClient, GrpcConnectionConfig


def _load_env_credentials() -> list[str]:
    loaded: list[str] = []
    candidates = [
        PROJECT_ROOT / "api" / ".env",
        PROJECT_ROOT / ".env",
        Path.cwd() / "api" / ".env",
        Path.cwd() / ".env",
    ]

    for path in candidates:
        if not path.is_file():
            continue
        loaded.append(str(path))
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value

    if "HYPER_API_KEY" not in os.environ and "API_KEY" in os.environ:
        os.environ["HYPER_API_KEY"] = os.environ["API_KEY"]
    if "RPC_GATEWAY_KEY" not in os.environ and "RPC_KEY" in os.environ:
        os.environ["RPC_GATEWAY_KEY"] = os.environ["RPC_KEY"]
    if "UNIFIED_STREAM_KEY" not in os.environ and "UNIFIED_KEY" in os.environ:
        os.environ["UNIFIED_STREAM_KEY"] = os.environ["UNIFIED_KEY"]
    if "DISK_STREAM_KEY" not in os.environ and "UNIFIED_KEY" in os.environ:
        os.environ["DISK_STREAM_KEY"] = os.environ["UNIFIED_KEY"]
    if "GRPC_STREAM_KEY" not in os.environ and "RPC_GATEWAY_KEY" in os.environ:
        os.environ["GRPC_STREAM_KEY"] = os.environ["RPC_GATEWAY_KEY"]
    if "GRPC_STREAM_KEY" not in os.environ and "HYPER_API_KEY" in os.environ:
        os.environ["GRPC_STREAM_KEY"] = os.environ["HYPER_API_KEY"]
    if "HYPER_API_KEY" not in os.environ and "RPC_GATEWAY_KEY" in os.environ:
        os.environ["HYPER_API_KEY"] = os.environ["RPC_GATEWAY_KEY"]
    return loaded


def _clean_key(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return None
    if cleaned.startswith("${") and cleaned.endswith("}"):
        return None
    if any(char in cleaned for char in {" ", "\t", "\n", "<", ">"}):
        return None
    return cleaned


def _mask_key(key: str | None) -> str | None:
    cleaned = _clean_key(key)
    if not cleaned:
        return None
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _split_key_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in re.split(r"[,\s]+", raw.strip()) if part]


def _pick_key(explicit: str | None, candidates: list[tuple[str, str | None]]) -> tuple[str | None, str | None]:
    cleaned = _clean_key(explicit)
    if cleaned:
        return cleaned, "cli"
    for source, value in candidates:
        cleaned = _clean_key(value)
        if cleaned:
            return cleaned, source
    return None, None


def _append_query(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def _rpc_check(*, url: str, api_key: str | None, timeout_s: float, verify_tls: bool) -> dict[str, Any]:
    start = time.perf_counter()
    if not api_key:
        return {"ok": False, "error": "missing_key"}
    try:
        with httpx.Client(timeout=timeout_s, verify=verify_tls) as client:
            response = client.post(
                url,
                headers={"content-type": "application/json", "x-api-key": api_key},
                json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            )
        latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
        payload: dict[str, Any] | Any
        try:
            payload = response.json()
        except Exception:
            payload = None
        has_result = isinstance(payload, dict) and "result" in payload
        return {
            "ok": response.status_code == 200 and has_result,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "has_result": has_result,
            "error": None if response.status_code == 200 and has_result else response.text[:200],
        }
    except Exception as exc:  # pragma: no cover - network failures vary
        return {"ok": False, "error": str(exc), "latency_ms": round((time.perf_counter() - start) * 1000.0, 3)}


def _unified_check(*, base_url: str, api_key: str | None, timeout_s: float, verify_tls: bool) -> dict[str, Any]:
    start = time.perf_counter()
    if not api_key:
        return {"ok": False, "error": "missing_key"}
    target = f"{base_url.rstrip('/')}/api/v1/unified/stats"
    try:
        with httpx.Client(timeout=timeout_s, verify=verify_tls) as client:
            response = client.get(target, headers={"x-api-key": api_key, "accept": "application/json"})
        latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
        is_json = "json" in response.headers.get("content-type", "").lower()
        return {
            "ok": response.status_code == 200 and is_json,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": None if response.status_code == 200 and is_json else response.text[:200],
        }
    except Exception as exc:  # pragma: no cover - network failures vary
        return {"ok": False, "error": str(exc), "latency_ms": round((time.perf_counter() - start) * 1000.0, 3)}


def _disk_ws_check(*, ws_url: str, api_key: str | None, timeout_s: float, verify_tls: bool) -> dict[str, Any]:
    if not api_key:
        return {"ok": False, "error": "missing_key"}
    ssl_ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()  # noqa: S323
    failures: list[dict[str, Any]] = []

    # Attempt 1: query param auth
    start = time.perf_counter()
    query_url = _append_query(ws_url, "api_key", api_key)
    try:
        with ws_connect(query_url, ssl=ssl_ctx, max_size=None, open_timeout=timeout_s):
            return {
                "ok": True,
                "auth_mode": "query_param",
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
    except Exception as exc:  # pragma: no cover - network failures vary
        failures.append(
            {
                "auth_mode": "query_param",
                "error": str(exc),
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
        )

    # Attempt 2: x-api-key header
    start = time.perf_counter()
    try:
        with ws_connect(
            ws_url,
            ssl=ssl_ctx,
            max_size=None,
            open_timeout=timeout_s,
            additional_headers={"x-api-key": api_key},
        ):
            return {
                "ok": True,
                "auth_mode": "header_x_api_key",
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
    except Exception as exc:  # pragma: no cover - network failures vary
        failures.append(
            {
                "auth_mode": "header_x_api_key",
                "error": str(exc),
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
        )

    return {"ok": False, "attempts": failures, "error": "all_ws_auth_modes_failed"}


def _grpc_check(
    *,
    target: str,
    server_name: str | None,
    plaintext: bool,
    api_key: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    start = time.perf_counter()
    if not api_key:
        return {"ok": False, "error": "missing_key"}
    client = GrpcClient(
        GrpcConnectionConfig(
            target=target,
            timeout_s=timeout_s,
            use_tls=not plaintext,
            server_name=server_name,
            api_key=api_key,
        )
    )
    try:
        health = client.health_check(service="")
        return {
            "ok": True,
            "status": health.get("status"),
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
        }
    except Exception as exc:  # pragma: no cover - network failures vary
        return {"ok": False, "error": str(exc), "latency_ms": round((time.perf_counter() - start) * 1000.0, 3)}


def build_parser() -> argparse.ArgumentParser:
    cfg = SDKConfig()
    parser = argparse.ArgumentParser(
        description="Preflight auth/key-scope checks for rpc, unified, disk ws, and grpc endpoints."
    )
    parser.add_argument("--rpc-url", default=os.getenv("ALEATORIC_RPC_URL", cfg.rpc_url))
    parser.add_argument("--stream-url", default=os.getenv("ALEATORIC_STREAM_URL", cfg.unified_stream_url))
    parser.add_argument("--ws-url", default=os.getenv("ALEATORIC_DISK_WS_URL", cfg.ws_url))
    parser.add_argument("--grpc-target", default=os.getenv("ALEATORIC_GRPC_TARGET", cfg.grpc_target))
    parser.add_argument("--grpc-server-name", default=os.getenv("ALEATORIC_GRPC_SERVER_NAME", cfg.grpc_server_name))
    parser.add_argument("--grpc-plaintext", action="store_true", default=False)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=cfg.verify_tls,
        help="Verify TLS certificates (enabled by default).",
    )
    parser.add_argument("--rpc-key", default=None)
    parser.add_argument("--unified-key", default=None)
    parser.add_argument("--ws-key", default=None)
    parser.add_argument("--grpc-key", default=None)
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit non-zero when any check fails (enabled by default).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    loaded_env_files = _load_env_credentials()
    args = build_parser().parse_args(argv)

    api_keys_list = _split_key_list(os.getenv("api_keys"))
    first_list_key = api_keys_list[0] if api_keys_list else None
    generic_key = os.getenv("HYPER_API_KEY") or os.getenv("API_KEY")

    rpc_key, rpc_source = _pick_key(
        args.rpc_key,
        [
            ("RPC_GATEWAY_KEY", os.getenv("RPC_GATEWAY_KEY")),
            ("RPC_KEY", os.getenv("RPC_KEY")),
            ("HYPER_API_KEY|API_KEY", generic_key),
            ("api_keys[0]", first_list_key),
        ],
    )
    unified_key, unified_source = _pick_key(
        args.unified_key,
        [
            ("UNIFIED_STREAM_KEY", os.getenv("UNIFIED_STREAM_KEY")),
            ("UNIFIED_KEY", os.getenv("UNIFIED_KEY")),
            ("HYPER_API_KEY|API_KEY", generic_key),
            ("api_keys[0]", first_list_key),
        ],
    )
    ws_key, ws_source = _pick_key(
        args.ws_key,
        [
            ("DISK_STREAM_KEY", os.getenv("DISK_STREAM_KEY")),
            ("UNIFIED_STREAM_KEY", os.getenv("UNIFIED_STREAM_KEY")),
            ("UNIFIED_KEY", os.getenv("UNIFIED_KEY")),
            ("HYPER_API_KEY|API_KEY", generic_key),
            ("api_keys[0]", first_list_key),
        ],
    )
    grpc_key, grpc_source = _pick_key(
        args.grpc_key,
        [
            ("ALEATORIC_GRPC_KEY", os.getenv("ALEATORIC_GRPC_KEY")),
            ("RPC_GATEWAY_KEY", os.getenv("RPC_GATEWAY_KEY")),
            ("RPC_KEY", os.getenv("RPC_KEY")),
            ("GRPC_STREAM_KEY", os.getenv("GRPC_STREAM_KEY")),
            ("UNIFIED_STREAM_KEY", os.getenv("UNIFIED_STREAM_KEY")),
            ("UNIFIED_KEY", os.getenv("UNIFIED_KEY")),
            ("HYPER_API_KEY|API_KEY", generic_key),
            ("api_keys[0]", first_list_key),
        ],
    )

    checks = {
        "rpc": _rpc_check(url=args.rpc_url, api_key=rpc_key, timeout_s=args.timeout, verify_tls=args.verify_tls),
        "unified": _unified_check(
            base_url=args.stream_url,
            api_key=unified_key,
            timeout_s=args.timeout,
            verify_tls=args.verify_tls,
        ),
        "disk_ws": _disk_ws_check(ws_url=args.ws_url, api_key=ws_key, timeout_s=args.timeout, verify_tls=args.verify_tls),
        "grpc": _grpc_check(
            target=args.grpc_target,
            server_name=args.grpc_server_name,
            plaintext=args.grpc_plaintext,
            api_key=grpc_key,
            timeout_s=args.timeout,
        ),
    }

    overall_ok = all(bool(result.get("ok")) for result in checks.values())
    output: dict[str, Any] = {
        "loaded_env_files": loaded_env_files,
        "targets": {
            "rpc_url": args.rpc_url,
            "stream_url": args.stream_url,
            "ws_url": args.ws_url,
            "grpc_target": args.grpc_target,
            "grpc_server_name": args.grpc_server_name,
            "grpc_plaintext": args.grpc_plaintext,
        },
        "keys": {
            "rpc": {"source": rpc_source, "masked": _mask_key(rpc_key), "present": bool(rpc_key)},
            "unified": {"source": unified_source, "masked": _mask_key(unified_key), "present": bool(unified_key)},
            "disk_ws": {"source": ws_source, "masked": _mask_key(ws_key), "present": bool(ws_key)},
            "grpc": {"source": grpc_source, "masked": _mask_key(grpc_key), "present": bool(grpc_key)},
        },
        "checks": checks,
        "overall_ok": overall_ok,
    }

    print(json.dumps(output, indent=2))
    if args.strict and not overall_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
