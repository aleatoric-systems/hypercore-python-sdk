#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import grpc

# Allow running directly via: python3 examples/grpc_liquidations_live.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hypercore_sdk import SDKConfig
from hypercore_sdk.example_auth import grpc_key_candidates, load_env_credentials, pick_key
from hypercore_sdk.grpc_client import GrpcClient, GrpcConnectionConfig
from hypercore_sdk.proto import hypercore_bridge_pb2 as bridge_pb2
from hypercore_sdk.proto import hypercore_bridge_pb2_grpc as bridge_pb2_grpc


def _event_payload(item: Any) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    ts_ms = int(item.ts_ms) if int(item.ts_ms) > 0 else None
    ingest_latency_ms = float(max(0, now_ms - ts_ms)) if ts_ms is not None else None
    return {
        "symbol": item.symbol,
        "tx_hash": item.tx_hash,
        "block_number": item.block_number,
        "log_index": item.log_index,
        "ts_ms": ts_ms,
        "source": item.source,
        "channel": item.channel,
        "address": item.address,
        "topic0": item.topic0,
        "data": item.data,
        "ingest_latency_ms": ingest_latency_ms,
    }


def build_parser() -> argparse.ArgumentParser:
    load_env_credentials(PROJECT_ROOT)
    cfg = SDKConfig()

    parser = argparse.ArgumentParser(
        description=(
            "Live gRPC liquidation feed consumer. "
            "Consumes PriceService/StreamLiquidations and emits JSON lines."
        )
    )
    parser.add_argument("--target", default=os.getenv("ALEATORIC_GRPC_TARGET", cfg.grpc_target), help="gRPC host:port")
    parser.add_argument("--coin", default="BTC", help="Asset symbol.")
    parser.add_argument("--heartbeat-s", type=int, default=10)
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Stop after N output events (0 means stream forever).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
    )
    parser.add_argument("--server-name", default=os.getenv("ALEATORIC_GRPC_SERVER_NAME", cfg.grpc_server_name), help="TLS SNI/server name override")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-RPC timeout for bounded runs.")
    parser.add_argument("--plaintext", action="store_true", default=False, help="Disable TLS.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    api_key = pick_key(args.api_key, [*grpc_key_candidates(), ("SDKConfig.api_key", SDKConfig().api_key)]).value

    grpc_cfg = GrpcConnectionConfig(
        target=args.target,
        timeout_s=float(args.timeout),
        use_tls=not args.plaintext,
        server_name=args.server_name,
        api_key=api_key,
    )
    client = GrpcClient(grpc_cfg)

    request = bridge_pb2.StreamLiquidationsRequest(
        coin=args.coin,
        heartbeat_s=max(1, int(args.heartbeat_s)),
    )

    total = 0
    emitted = 0

    try:
        with client._channel() as channel:  # Reuse SDK-authenticated channel config for live stream.
            stub = bridge_pb2_grpc.PriceServiceStub(channel)
            timeout = None if int(args.max_events) <= 0 else max(float(args.timeout), 2.0)
            stream = stub.StreamLiquidations(request, timeout=timeout, metadata=client._metadata())

            for item in stream:
                total += 1
                event = _event_payload(item)

                emitted += 1
                print(json.dumps(event, separators=(",", ":"), sort_keys=True), flush=True)

                if int(args.max_events) > 0 and emitted >= int(args.max_events):
                    break

        return 0
    except grpc.RpcError as exc:
        print(f"gRPC stream error: code={exc.code()} details={exc.details()}", file=sys.stderr)
        print(
            "Hint: ensure liquidation topics are configured on the bridge "
            "(--liquidation-topics) and this API key is allowed.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(f"\nStopped after {total} received events ({emitted} emitted).", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
