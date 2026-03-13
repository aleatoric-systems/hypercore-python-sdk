from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .api import HyperCoreAPI
from .config import SDKConfig
from .grpc_client import GrpcClient, GrpcConnectionConfig
from .speed import run_grpc_health_speed_test, run_rpc_speed_test, run_ws_speed_test
from .templates import render_nginx_grpc_template
from .unified_stream import UnifiedStreamClient
from .ws import get_price_from_ws

DEFAULT_CFG = SDKConfig()


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _add_common_network_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-key", default=None, help="API key for x-api-key header")
    parser.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_CFG.verify_tls,
        help="Verify TLS certificates (enabled by default).",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds.")


def _add_common_grpc_args(parser: argparse.ArgumentParser, *, default_timeout: float) -> None:
    parser.add_argument("--target", default=DEFAULT_CFG.grpc_target, help="host:port")
    parser.add_argument(
        "--plaintext",
        action="store_true",
        default=False,
        help="Disable TLS (local/private testing only).",
    )
    parser.add_argument("--server-name", default=None, help="TLS SNI/server name override")
    parser.add_argument(
        "--ca-cert",
        default=None,
        help="Optional CA certificate file for private or self-managed PKI.",
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=default_timeout)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hypercore-sdk")
    sub = parser.add_subparsers(dest="command", required=True)

    price = sub.add_parser("price", help="Price access helpers.")
    price_sub = price.add_subparsers(dest="price_cmd", required=True)

    price_ws = price_sub.add_parser("ws", help="Get price from WebSocket stream.")
    price_ws.add_argument("--ws-url", default=DEFAULT_CFG.ws_url)
    price_ws.add_argument("--coin", default="BTC")
    price_ws.add_argument(
        "--subscription",
        default="allMids",
        choices=["allMids", "trades", "l2Book"],
        help="WebSocket subscription type.",
    )
    price_ws.add_argument("--raw-message", action="store_true", default=False)
    _add_common_network_args(price_ws)

    price_info = price_sub.add_parser("info", help="Get price from the info API (allMids).")
    price_info.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    price_info.add_argument("--coin", default="BTC")
    _add_common_network_args(price_info)

    intel = sub.add_parser("intel", help="High-value market/user intelligence surfaces.")
    intel_sub = intel.add_subparsers(dest="intel_cmd", required=True)

    intel_market = intel_sub.add_parser("market", help="Get market snapshot (mid, top-of-book, asset ctx).")
    intel_market.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    intel_market.add_argument("--coin", default="BTC")
    _add_common_network_args(intel_market)

    intel_user = intel_sub.add_parser("user-flow", help="Get user state + open orders + fill summary.")
    intel_user.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    intel_user.add_argument("--address", required=True)
    intel_user.add_argument("--dex", default="")
    _add_common_network_args(intel_user)

    intel_fills = intel_sub.add_parser("fills", help="Get user fills (optionally by time range).")
    intel_fills.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    intel_fills.add_argument("--address", required=True)
    intel_fills.add_argument("--start-time-ms", type=int, default=None)
    intel_fills.add_argument("--end-time-ms", type=int, default=None)
    intel_fills.add_argument("--aggregate-by-time", action="store_true", default=False)
    _add_common_network_args(intel_fills)

    intel_funding = intel_sub.add_parser("funding", help="Get funding rows and aggregate stats for a coin.")
    intel_funding.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    intel_funding.add_argument("--coin", required=True)
    intel_funding.add_argument("--start-time-ms", type=int, required=True)
    intel_funding.add_argument("--end-time-ms", type=int, default=None)
    _add_common_network_args(intel_funding)

    intel_activity = intel_sub.add_parser("activity", help="Get user activity snapshot (fills + ledger + state).")
    intel_activity.add_argument("--info-url", default=DEFAULT_CFG.info_url)
    intel_activity.add_argument("--address", required=True)
    intel_activity.add_argument("--start-time-ms", type=int, required=True)
    intel_activity.add_argument("--end-time-ms", type=int, default=None)
    intel_activity.add_argument("--dex", default="")
    _add_common_network_args(intel_activity)

    rpc = sub.add_parser("rpc", help="JSON-RPC API access.")
    rpc_sub = rpc.add_subparsers(dest="rpc_cmd", required=True)

    rpc_call = rpc_sub.add_parser("call", help="Run a JSON-RPC method call.")
    rpc_call.add_argument("--rpc-url", default=DEFAULT_CFG.rpc_url)
    rpc_call.add_argument("--method", required=True)
    rpc_call.add_argument("--params", default="[]", help='JSON array, for example \'["latest"]\'')
    _add_common_network_args(rpc_call)

    stream = sub.add_parser("stream", help="Dedicated unified event stream API.")
    stream_sub = stream.add_subparsers(dest="stream_cmd", required=True)

    stream_stats = stream_sub.add_parser("stats", help="Get unified stream aggregate statistics.")
    stream_stats.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    _add_common_network_args(stream_stats)

    stream_events = stream_sub.add_parser("events", help="Get unified stream pre-decoded events (batch).")
    stream_events.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_events.add_argument("--limit", type=int, default=200)
    _add_common_network_args(stream_events)

    stream_liquidations = stream_sub.add_parser("liquidations", help="Get unified liquidation_warning events.")
    stream_liquidations.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_liquidations.add_argument("--limit", type=int, default=200)
    _add_common_network_args(stream_liquidations)

    stream_cascades = stream_sub.add_parser("cascades", help="Get derived liquidation_cascade events.")
    stream_cascades.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_cascades.add_argument("--limit", type=int, default=200)
    _add_common_network_args(stream_cascades)

    stream_sse = stream_sub.add_parser("sse", help="Read a bounded number of events from unified stream SSE.")
    stream_sse.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_sse.add_argument("--max-events", type=int, default=20)
    _add_common_network_args(stream_sse)

    stream_pulse = stream_sub.add_parser("consensus-pulse", help="Get unified consensus pulse metrics.")
    stream_pulse.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    _add_common_network_args(stream_pulse)

    stream_all_mids = stream_sub.add_parser("all-mids", help="Get browser-safe allMids snapshot from unified stream.")
    stream_all_mids.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_all_mids.add_argument("--dex", default="")
    _add_common_network_args(stream_all_mids)

    stream_l2_book = stream_sub.add_parser("l2-book", help="Get browser-safe canonical L2 book snapshot from unified stream.")
    stream_l2_book.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_l2_book.add_argument("--coin", required=True)
    stream_l2_book.add_argument("--dex", default="")
    stream_l2_book.add_argument("--depth", type=int, default=None)
    _add_common_network_args(stream_l2_book)

    stream_asset_contexts = stream_sub.add_parser("asset-contexts", help="Get funding/OI/24h volume asset contexts from unified stream.")
    stream_asset_contexts.add_argument("--stream-url", default=DEFAULT_CFG.unified_stream_url)
    stream_asset_contexts.add_argument("--coin", default=None)
    stream_asset_contexts.add_argument("--dex", default="")
    _add_common_network_args(stream_asset_contexts)

    grpc = sub.add_parser("grpc", help="gRPC setup and diagnostics.")
    grpc_sub = grpc.add_subparsers(dest="grpc_cmd", required=True)

    grpc_health = grpc_sub.add_parser("health", help="Run gRPC health check.")
    grpc_health.add_argument("--service", default="")
    _add_common_grpc_args(grpc_health, default_timeout=5.0)

    grpc_list = grpc_sub.add_parser("list-services", help="List services via gRPC reflection.")
    _add_common_grpc_args(grpc_list, default_timeout=5.0)

    grpc_invoke = grpc_sub.add_parser("invoke", help="Invoke a gRPC method using grpcurl.")
    grpc_invoke.add_argument("--target", default=DEFAULT_CFG.grpc_target, help="host:port")
    grpc_invoke.add_argument("--method", required=True, help="Fully qualified method, for example package.Service/Method")
    grpc_invoke.add_argument("--request-json", default="{}")
    grpc_invoke.add_argument(
        "--plaintext",
        action="store_true",
        default=False,
        help="Disable TLS (local/private testing only).",
    )
    grpc_invoke.add_argument("--insecure", action="store_true", default=False, help="Skip TLS cert verification in grpcurl")
    grpc_invoke.add_argument("--server-name", default=None, help="TLS SNI/authority override for grpcurl")
    grpc_invoke.add_argument("--ca-cert", default=None, help="Optional CA certificate file for grpcurl TLS validation")
    grpc_invoke.add_argument("--proto", default=None)
    grpc_invoke.add_argument("--import-path", default=None)
    grpc_invoke.add_argument("--api-key", default=None)
    grpc_invoke.add_argument("--timeout", type=float, default=8.0)

    grpc_template = grpc_sub.add_parser("setup-template", help="Print nginx gRPC gateway template.")
    grpc_template.add_argument("--server-name", required=True, help="Public DNS name.")
    grpc_template.add_argument("--upstream", default="127.0.0.1:50051", help="gRPC upstream target.")

    grpc_price = grpc_sub.add_parser("price", help="Get mid price from bridge gRPC.")
    grpc_price.add_argument("--coin", default="BTC")
    _add_common_grpc_args(grpc_price, default_timeout=5.0)

    grpc_stream = grpc_sub.add_parser("stream", help="Stream prices from bridge gRPC.")
    grpc_stream.add_argument("--coin", default="BTC")
    grpc_stream.add_argument("--subscription", default="allMids", choices=["allMids", "trades", "l2Book"])
    grpc_stream.add_argument("--heartbeat-s", type=int, default=10)
    grpc_stream.add_argument("--max-messages", type=int, default=5)
    _add_common_grpc_args(grpc_stream, default_timeout=30.0)

    grpc_liquidations = grpc_sub.add_parser("liquidations", help="Stream liquidation events from bridge gRPC.")
    grpc_liquidations.add_argument("--coin", default="BTC")
    grpc_liquidations.add_argument("--heartbeat-s", type=int, default=1)
    grpc_liquidations.add_argument("--max-messages", type=int, default=20)
    _add_common_grpc_args(grpc_liquidations, default_timeout=30.0)

    grpc_block = grpc_sub.add_parser("block-number", help="Get block number from bridge gRPC.")
    _add_common_grpc_args(grpc_block, default_timeout=5.0)

    speed = sub.add_parser("speed", help="Latency/speed tests.")
    speed_sub = speed.add_subparsers(dest="speed_cmd", required=True)

    speed_rpc = speed_sub.add_parser("rpc", help="JSON-RPC latency test.")
    speed_rpc.add_argument("--rpc-url", default=DEFAULT_CFG.rpc_url)
    speed_rpc.add_argument("--count", type=int, default=30)
    _add_common_network_args(speed_rpc)

    speed_ws = speed_sub.add_parser("ws", help="WebSocket connect+first-price latency test.")
    speed_ws.add_argument("--ws-url", default=DEFAULT_CFG.ws_url)
    speed_ws.add_argument("--coin", default="BTC")
    speed_ws.add_argument(
        "--subscription",
        default="allMids",
        choices=["allMids", "trades", "l2Book"],
    )
    speed_ws.add_argument("--count", type=int, default=10)
    _add_common_network_args(speed_ws)

    speed_grpc = speed_sub.add_parser("grpc-health", help="gRPC health-check latency test.")
    speed_grpc.add_argument("--service", default="")
    speed_grpc.add_argument("--count", type=int, default=20)
    _add_common_grpc_args(speed_grpc, default_timeout=5.0)

    return parser


def _sdk_cfg_from_args(
    args: argparse.Namespace,
    *,
    rpc_url: str | None = None,
    info_url: str | None = None,
    ws_url: str | None = None,
    unified_stream_url: str | None = None,
) -> SDKConfig:
    return SDKConfig(
        rpc_url=rpc_url or DEFAULT_CFG.rpc_url,
        ws_url=ws_url or DEFAULT_CFG.ws_url,
        info_url=info_url or DEFAULT_CFG.info_url,
        unified_stream_url=unified_stream_url or DEFAULT_CFG.unified_stream_url,
        api_key=args.api_key,
        timeout_s=args.timeout,
        verify_tls=args.verify_tls,
    )


def _grpc_cfg_from_args(args: argparse.Namespace) -> GrpcConnectionConfig:
    return GrpcConnectionConfig(
        target=args.target,
        timeout_s=args.timeout,
        use_tls=not args.plaintext,
        server_name=args.server_name,
        api_key=args.api_key,
        ca_cert_path=args.ca_cert,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "price" and args.price_cmd == "ws":
            result = asyncio.run(
                get_price_from_ws(
                    ws_url=args.ws_url,
                    coin=args.coin,
                    subscription_type=args.subscription,
                    timeout_s=args.timeout,
                    api_key=args.api_key,
                )
            )
            if not args.raw_message:
                result = {
                    "coin": result["coin"],
                    "price": result["price"],
                    "channel": result["channel"],
                    "latency_ms": result["latency_ms"],
                }
            _print_json(result)
            return 0

        if args.command == "price" and args.price_cmd == "info":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                price = api.coin_mid(args.coin)
            _print_json({"coin": args.coin, "price": price, "source": "info/allMids"})
            return 0

        if args.command == "intel" and args.intel_cmd == "market":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                _print_json(api.market_snapshot(args.coin))
            return 0

        if args.command == "intel" and args.intel_cmd == "user-flow":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                _print_json(api.user_flow_snapshot(args.address, dex=args.dex))
            return 0

        if args.command == "intel" and args.intel_cmd == "fills":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                if args.start_time_ms is None:
                    fills = api.user_fills(args.address)
                else:
                    fills = api.user_fills_by_time(
                        args.address,
                        start_time_ms=args.start_time_ms,
                        end_time_ms=args.end_time_ms,
                        aggregate_by_time=args.aggregate_by_time,
                    )
                _print_json({"fills": fills, "summary": api.summarize_fills(fills)})
            return 0

        if args.command == "intel" and args.intel_cmd == "funding":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                _print_json(
                    api.funding_snapshot(
                        args.coin,
                        start_time_ms=args.start_time_ms,
                        end_time_ms=args.end_time_ms,
                    )
                )
            return 0

        if args.command == "intel" and args.intel_cmd == "activity":
            cfg = _sdk_cfg_from_args(args, info_url=args.info_url)
            with HyperCoreAPI(cfg) as api:
                _print_json(
                    api.user_activity_snapshot(
                        args.address,
                        start_time_ms=args.start_time_ms,
                        end_time_ms=args.end_time_ms,
                        dex=args.dex,
                    )
                )
            return 0

        if args.command == "rpc" and args.rpc_cmd == "call":
            cfg = _sdk_cfg_from_args(args, rpc_url=args.rpc_url)
            with HyperCoreAPI(cfg) as api:
                params = json.loads(args.params)
                if not isinstance(params, list):
                    raise ValueError("--params must be a JSON array")
                result = api.rpc_call(args.method, params=params)
            _print_json({"method": args.method, "result": result})
            return 0

        if args.command == "stream" and args.stream_cmd == "stats":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.stats())
            return 0

        if args.command == "stream" and args.stream_cmd == "events":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.events(limit=args.limit))
            return 0

        if args.command == "stream" and args.stream_cmd == "liquidations":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.liquidations(limit=args.limit))
            return 0

        if args.command == "stream" and args.stream_cmd == "cascades":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.liquidation_cascades(limit=args.limit))
            return 0

        if args.command == "stream" and args.stream_cmd == "sse":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json({"events": list(stream_client.sse_events(max_events=args.max_events))})
            return 0

        if args.command == "stream" and args.stream_cmd == "consensus-pulse":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.consensus_pulse())
            return 0

        if args.command == "stream" and args.stream_cmd == "all-mids":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.all_mids(dex=args.dex))
            return 0

        if args.command == "stream" and args.stream_cmd == "l2-book":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.l2_book(args.coin, dex=args.dex, depth=args.depth))
            return 0

        if args.command == "stream" and args.stream_cmd == "asset-contexts":
            cfg = _sdk_cfg_from_args(args, unified_stream_url=args.stream_url)
            with UnifiedStreamClient(cfg) as stream_client:
                _print_json(stream_client.asset_contexts(coin=args.coin, dex=args.dex))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "health":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(grpc_client.health_check(service=args.service))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "list-services":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json({"services": grpc_client.list_services()})
            return 0

        if args.command == "grpc" and args.grpc_cmd == "invoke":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            result = grpc_client.grpcurl_invoke(
                method=args.method,
                request_json=args.request_json,
                proto=args.proto,
                import_path=args.import_path,
                insecure_tls=args.insecure,
            )
            _print_json(result)
            return 0 if result["returncode"] == 0 else 2

        if args.command == "grpc" and args.grpc_cmd == "setup-template":
            print(render_nginx_grpc_template(args.server_name, args.upstream))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "price":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(grpc_client.get_mid_price(coin=args.coin))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "stream":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(
                {
                    "messages": grpc_client.stream_mids(
                        coin=args.coin,
                        subscription=args.subscription,
                        heartbeat_s=args.heartbeat_s,
                        max_messages=args.max_messages,
                    )
                }
            )
            return 0

        if args.command == "grpc" and args.grpc_cmd == "liquidations":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(
                {
                    "messages": grpc_client.stream_liquidations(
                        coin=args.coin,
                        heartbeat_s=args.heartbeat_s,
                        max_messages=args.max_messages,
                    )
                }
            )
            return 0

        if args.command == "grpc" and args.grpc_cmd == "block-number":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(grpc_client.get_block_number())
            return 0

        if args.command == "speed" and args.speed_cmd == "rpc":
            cfg = _sdk_cfg_from_args(args, rpc_url=args.rpc_url)
            with HyperCoreAPI(cfg) as api:
                _print_json(run_rpc_speed_test(api, count=args.count))
            return 0

        if args.command == "speed" and args.speed_cmd == "ws":
            _print_json(
                run_ws_speed_test(
                    ws_url=args.ws_url,
                    coin=args.coin,
                    subscription_type=args.subscription,
                    count=args.count,
                    timeout_s=args.timeout,
                    api_key=args.api_key,
                )
            )
            return 0

        if args.command == "speed" and args.speed_cmd == "grpc-health":
            grpc_client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(run_grpc_health_speed_test(grpc_client, count=args.count, service=args.service))
            return 0

        parser.print_help()
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
