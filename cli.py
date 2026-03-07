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
from .trading import HyperCoreTradingClient, TradingConfig, list_trading_actions
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


def _add_common_trade_args(parser: argparse.ArgumentParser, *, default_timeout: float) -> None:
    parser.add_argument("--base-url", default=None, help="Hyperliquid API base URL (env: HYPER_TRADING_BASE_URL).")
    parser.add_argument("--private-key", default=None, help="Signer private key (env: HYPER_PRIVATE_KEY).")
    parser.add_argument("--vault-address", default=None, help="Vault address override (env: HYPER_VAULT_ADDRESS).")
    parser.add_argument("--account-address", default=None, help="Account address override (env: HYPER_ACCOUNT_ADDRESS).")
    parser.add_argument("--timeout", type=float, default=default_timeout, help="Timeout in seconds.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hypercore-sdk")
    sub = parser.add_subparsers(dest="command", required=True)

    price = sub.add_parser("price", help="Price access helpers.")
    price_sub = price.add_subparsers(dest="price_cmd", required=True)

    price_ws = price_sub.add_parser("ws", help="Get price from WebSocket stream.")
    price_ws.add_argument("--ws-url", default="wss://api.hyperliquid.xyz/ws")
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
    price_info.add_argument("--info-url", default="https://api.hyperliquid.xyz/info")
    price_info.add_argument("--coin", default="BTC")
    _add_common_network_args(price_info)

    rpc = sub.add_parser("rpc", help="JSON-RPC API access.")
    rpc_sub = rpc.add_subparsers(dest="rpc_cmd", required=True)

    rpc_call = rpc_sub.add_parser("call", help="Run a JSON-RPC method call.")
    rpc_call.add_argument("--rpc-url", default=DEFAULT_CFG.rpc_url)
    rpc_call.add_argument("--method", required=True)
    rpc_call.add_argument("--params", default="[]", help='JSON array, for example \'["latest"]\'')
    _add_common_network_args(rpc_call)

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

    grpc_block = grpc_sub.add_parser("block-number", help="Get block number from bridge gRPC.")
    _add_common_grpc_args(grpc_block, default_timeout=5.0)

    speed = sub.add_parser("speed", help="Latency/speed tests.")
    speed_sub = speed.add_subparsers(dest="speed_cmd", required=True)

    speed_rpc = speed_sub.add_parser("rpc", help="JSON-RPC latency test.")
    speed_rpc.add_argument("--rpc-url", default=DEFAULT_CFG.rpc_url)
    speed_rpc.add_argument("--count", type=int, default=30)
    _add_common_network_args(speed_rpc)

    speed_ws = speed_sub.add_parser("ws", help="WebSocket connect+first-price latency test.")
    speed_ws.add_argument("--ws-url", default="wss://api.hyperliquid.xyz/ws")
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

    trade = sub.add_parser("trade", help="Signed trading interfaces and actions.")
    trade_sub = trade.add_subparsers(dest="trade_cmd", required=True)

    trade_actions = trade_sub.add_parser("actions", help="List all available exchange/info methods.")
    trade_actions.add_argument("--interface", choices=["exchange", "info", "all"], default="all")

    trade_meta = trade_sub.add_parser("meta", help="Show trading client metadata.")
    _add_common_trade_args(trade_meta, default_timeout=10.0)

    trade_call = trade_sub.add_parser("call", help="Call any exchange/info method by name.")
    trade_call.add_argument("--interface", choices=["exchange", "info"], required=True)
    trade_call.add_argument("--method", required=True)
    trade_call.add_argument("--kwargs-json", default="{}", help="JSON object of keyword args.")
    _add_common_trade_args(trade_call, default_timeout=10.0)

    trade_order = trade_sub.add_parser("order", help="Place limit/trigger order via signed exchange action.")
    trade_order.add_argument("--coin", required=True)
    trade_order.add_argument("--side", choices=["buy", "sell"], required=True)
    trade_order.add_argument("--size", type=float, required=True)
    trade_order.add_argument("--limit-px", type=float, required=True)
    trade_order.add_argument(
        "--order-type-json",
        default='{"limit":{"tif":"Gtc"}}',
        help='Order type payload as JSON (for example {"limit":{"tif":"Gtc"}}).',
    )
    trade_order.add_argument("--reduce-only", action="store_true", default=False)
    trade_order.add_argument("--cloid", default=None, help="Optional client order id as 0x... string.")
    trade_order.add_argument("--builder-json", default=None, help='Optional builder payload JSON: {"b":"0x...","f":10}')
    _add_common_trade_args(trade_order, default_timeout=10.0)

    trade_cancel = trade_sub.add_parser("cancel", help="Cancel order by oid.")
    trade_cancel.add_argument("--coin", required=True)
    trade_cancel.add_argument("--oid", type=int, required=True)
    _add_common_trade_args(trade_cancel, default_timeout=10.0)

    trade_cancel_cloid = trade_sub.add_parser("cancel-by-cloid", help="Cancel order by cloid (0x...).")
    trade_cancel_cloid.add_argument("--coin", required=True)
    trade_cancel_cloid.add_argument("--cloid", required=True)
    _add_common_trade_args(trade_cancel_cloid, default_timeout=10.0)

    return parser


def _sdk_cfg_from_args(args: argparse.Namespace, *, rpc_url: str | None = None, info_url: str | None = None, ws_url: str | None = None) -> SDKConfig:
    return SDKConfig(
        rpc_url=rpc_url or DEFAULT_CFG.rpc_url,
        ws_url=ws_url or DEFAULT_CFG.ws_url,
        info_url=info_url or DEFAULT_CFG.info_url,
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


def _trade_cfg_from_args(args: argparse.Namespace) -> TradingConfig:
    cfg = TradingConfig()
    return TradingConfig(
        base_url=args.base_url or cfg.base_url,
        private_key=args.private_key or cfg.private_key,
        vault_address=args.vault_address or cfg.vault_address,
        account_address=args.account_address or cfg.account_address,
        timeout_s=args.timeout,
        skip_ws=True,
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
            api = HyperCoreAPI(cfg)
            price = api.coin_mid(args.coin)
            _print_json({"coin": args.coin, "price": price, "source": "info/allMids"})
            return 0

        if args.command == "rpc" and args.rpc_cmd == "call":
            cfg = _sdk_cfg_from_args(args, rpc_url=args.rpc_url)
            api = HyperCoreAPI(cfg)
            params = json.loads(args.params)
            if not isinstance(params, list):
                raise ValueError("--params must be a JSON array")
            result = api.rpc_call(args.method, params=params)
            _print_json({"method": args.method, "result": result})
            return 0

        if args.command == "grpc" and args.grpc_cmd == "health":
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(client.health_check(service=args.service))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "list-services":
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json({"services": client.list_services()})
            return 0

        if args.command == "grpc" and args.grpc_cmd == "invoke":
            client = GrpcClient(_grpc_cfg_from_args(args))
            result = client.grpcurl_invoke(
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
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(client.get_mid_price(coin=args.coin))
            return 0

        if args.command == "grpc" and args.grpc_cmd == "stream":
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(
                {
                    "messages": client.stream_mids(
                        coin=args.coin,
                        subscription=args.subscription,
                        heartbeat_s=args.heartbeat_s,
                        max_messages=args.max_messages,
                    )
                }
            )
            return 0

        if args.command == "grpc" and args.grpc_cmd == "block-number":
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(client.get_block_number())
            return 0

        if args.command == "speed" and args.speed_cmd == "rpc":
            cfg = _sdk_cfg_from_args(args, rpc_url=args.rpc_url)
            api = HyperCoreAPI(cfg)
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
            client = GrpcClient(_grpc_cfg_from_args(args))
            _print_json(run_grpc_health_speed_test(client, count=args.count, service=args.service))
            return 0

        if args.command == "trade" and args.trade_cmd == "actions":
            _print_json(list_trading_actions(interface=args.interface))
            return 0

        if args.command == "trade" and args.trade_cmd == "meta":
            client = HyperCoreTradingClient(_trade_cfg_from_args(args))
            _print_json(client.metadata())
            return 0

        if args.command == "trade" and args.trade_cmd == "call":
            kwargs = json.loads(args.kwargs_json)
            if not isinstance(kwargs, dict):
                raise ValueError("--kwargs-json must be a JSON object")
            client = HyperCoreTradingClient(_trade_cfg_from_args(args))
            _print_json(client.invoke(args.interface, args.method, **kwargs))
            return 0

        if args.command == "trade" and args.trade_cmd == "order":
            order_type = json.loads(args.order_type_json)
            if not isinstance(order_type, dict):
                raise ValueError("--order-type-json must be a JSON object")
            builder = None
            if args.builder_json:
                builder = json.loads(args.builder_json)
                if not isinstance(builder, dict):
                    raise ValueError("--builder-json must be a JSON object")
            client = HyperCoreTradingClient(_trade_cfg_from_args(args))
            _print_json(
                client.order(
                    coin=args.coin,
                    side=args.side,
                    sz=args.size,
                    limit_px=args.limit_px,
                    order_type=order_type,
                    reduce_only=args.reduce_only,
                    cloid=args.cloid,
                    builder=builder,
                )
            )
            return 0

        if args.command == "trade" and args.trade_cmd == "cancel":
            client = HyperCoreTradingClient(_trade_cfg_from_args(args))
            _print_json(client.cancel(coin=args.coin, oid=args.oid))
            return 0

        if args.command == "trade" and args.trade_cmd == "cancel-by-cloid":
            client = HyperCoreTradingClient(_trade_cfg_from_args(args))
            _print_json(client.cancel_by_cloid(coin=args.coin, cloid=args.cloid))
            return 0

        parser.print_help()
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
