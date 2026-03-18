from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from .api import HyperCoreAPI
from .config import SDKConfig
from .grpc_client import GrpcClient, GrpcConnectionConfig
from .status import StatusClient
from .unified_stream import UnifiedStreamClient


JSONRPC_VERSION = "2.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def _jsonrpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": {"code": code, "message": message}}


def _result_text(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


@dataclass(slots=True)
class MCPClients:
    api: HyperCoreAPI
    grpc: GrpcClient
    unified: UnifiedStreamClient
    status: StatusClient


class HypercoreMCPServer:
    def __init__(self, cfg: SDKConfig | None = None, clients: MCPClients | None = None):
        self.cfg = cfg or SDKConfig()
        self._owned_clients = clients is None
        self.clients = clients or MCPClients(
            api=HyperCoreAPI(self.cfg),
            grpc=GrpcClient(
                GrpcConnectionConfig(
                    target=self.cfg.grpc_target,
                    timeout_s=self.cfg.timeout_s,
                    use_tls=self.cfg.grpc_tls,
                    server_name=self.cfg.grpc_server_name,
                    api_key=self.cfg.grpc_api_key or self.cfg.api_key,
                )
            ),
            unified=UnifiedStreamClient(self.cfg),
            status=StatusClient(self.cfg),
        )
        self.tools = self._build_tool_specs()

    def close(self) -> None:
        if not self._owned_clients:
            return
        self.clients.api.close()
        self.clients.unified.close()
        self.clients.status.close()

    def _build_tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "catalog_interfaces",
                "description": "Return the Hypernode service catalog, local coverage, and recommended low-latency paths.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "grpc_get_mid_price",
                "description": "Get a single cached-or-live mid price from the gRPC bridge.",
                "inputSchema": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": ["coin"], "additionalProperties": False},
            },
            {
                "name": "grpc_stream_mids_sample",
                "description": "Read a bounded sample from the gRPC market-data stream for allMids, trades, or l2Book.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string"},
                        "subscription": {"type": "string", "enum": ["allMids", "trades", "l2Book"]},
                        "max_messages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                        "heartbeat_s": {"type": "integer", "minimum": 1, "maximum": 60, "default": 5},
                    },
                    "required": ["coin", "subscription"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "grpc_get_block_number",
                "description": "Get the current block number from the gRPC bridge.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "grpc_stream_liquidations_sample",
                "description": "Read a bounded sample from the filtered liquidation stream.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string"},
                        "max_messages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                        "heartbeat_s": {"type": "integer", "minimum": 1, "maximum": 60, "default": 1},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "unified_get_stats",
                "description": "Fetch unified stream aggregate statistics, latency summaries, and microstructure metrics.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "unified_get_events",
                "description": "Fetch recent unified events with optional event_type and stream filters.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 50},
                        "event_type": {"type": "string"},
                        "stream": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "unified_get_liquidation_cascades",
                "description": "Fetch recent derived liquidation cascade events from the unified sidecar.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 50},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "unified_get_consensus_pulse",
                "description": "Fetch consensus pulse metrics, including block-height and Tokyo probe status.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "unified_get_all_mids",
                "description": "Fetch browser-safe allMids snapshot from the unified sidecar.",
                "inputSchema": {"type": "object", "properties": {"dex": {"type": "string"}}, "additionalProperties": False},
            },
            {
                "name": "unified_get_l2_book",
                "description": "Fetch browser-safe canonical L2 book snapshot from the unified sidecar.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"coin": {"type": "string"}, "dex": {"type": "string"}, "depth": {"type": "integer", "minimum": 1}},
                    "required": ["coin"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "unified_get_asset_contexts",
                "description": "Fetch browser-safe asset contexts including funding, OI, and 24h notional volume.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"coin": {"type": "string"}, "dex": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "status_get_public",
                "description": "Fetch the public delayed status snapshot.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "status_get_private",
                "description": "Fetch the private delayed status snapshot.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "rpc_call",
                "description": "Call a JSON-RPC method on the HyperCore node gateway.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"method": {"type": "string"}, "params": {"type": "array", "default": []}},
                    "required": ["method"],
                    "additionalProperties": False,
                },
            },
        ]

    def _catalog(self) -> dict[str, Any]:
        return {
            "service_catalog": {
                "grpc_bridge": {
                    "target": self.cfg.grpc_target,
                    "methods": ["GetMidPrice", "StreamMids", "GetBlockNumber", "StreamLiquidations"],
                },
                "unified_stream": {
                    "base_url": self.cfg.unified_stream_url,
                    "endpoints": [
                        "/healthz",
                        "/api/v1/unified/stats",
                        "/api/v1/unified/events",
                        "/api/v1/unified/stream",
                        "/api/v1/unified/consensus-pulse",
                        "/api/v1/unified/all-mids",
                        "/api/v1/unified/l2-book",
                        "/api/v1/unified/asset-contexts",
                    ],
                },
                "status_api": {
                    "base_url": self.cfg.status_url,
                    "endpoints": ["/healthz", "/api/v1/public/status", "/api/v1/status", "/api/v1/admin/tokens"],
                },
                "rpc_gateway": {
                    "url": self.cfg.rpc_url,
                    "common_methods": ["eth_blockNumber", "eth_getLogs", "eth_getBlockByNumber"],
                },
            },
            "indexed_locally": [
                "allMids",
                "trades",
                "l2Book top-of-book fields",
                "full browser-safe l2Book snapshots",
                "asset contexts from metaAndAssetCtxs",
                "derived l4_delta",
                "filtered liquidation_warning",
                "derived liquidation_cascade",
                "block_metrics",
                "consensus_pulse",
            ],
            "recommended_paths": {
                "mid_price": "grpc_get_mid_price or unified_get_all_mids",
                "trades": "grpc_stream_mids_sample(subscription=trades) or unified_get_events(stream=trades)",
                "l2_book": "unified_get_l2_book for browser-safe canonical snapshots; grpc_stream_mids_sample(subscription=l2Book) for top-of-book",
                "funding_oi_volume": "unified_get_asset_contexts",
                "liquidations": "grpc_stream_liquidations_sample first, unified_get_events(event_type=liquidation_warning) second, unified_get_liquidation_cascades for derived clusters",
            },
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        if name == "catalog_interfaces":
            return self._catalog()
        if name == "grpc_get_mid_price":
            return self.clients.grpc.get_mid_price(coin=str(args.get("coin", "BTC")))
        if name == "grpc_stream_mids_sample":
            return {
                "messages": self.clients.grpc.stream_mids(
                    coin=str(args.get("coin", "BTC")),
                    subscription=str(args.get("subscription", "allMids")),
                    heartbeat_s=int(args.get("heartbeat_s", 5)),
                    max_messages=int(args.get("max_messages", 5)),
                )
            }
        if name == "grpc_get_block_number":
            return self.clients.grpc.get_block_number()
        if name == "grpc_stream_liquidations_sample":
            return {
                "messages": self.clients.grpc.stream_liquidations(
                    coin=str(args.get("coin", "BTC")),
                    heartbeat_s=int(args.get("heartbeat_s", 1)),
                    max_messages=int(args.get("max_messages", 5)),
                )
            }
        if name == "unified_get_stats":
            return self.clients.unified.stats()
        if name == "unified_get_events":
            return self.clients.unified.events(
                limit=int(args.get("limit", 50)),
                event_type=str(args["event_type"]) if "event_type" in args and args["event_type"] is not None else None,
                stream=str(args["stream"]) if "stream" in args and args["stream"] is not None else None,
            )
        if name == "unified_get_liquidation_cascades":
            return self.clients.unified.liquidation_cascades(limit=int(args.get("limit", 50)))
        if name == "unified_get_consensus_pulse":
            return self.clients.unified.consensus_pulse()
        if name == "unified_get_all_mids":
            return self.clients.unified.all_mids(dex=str(args.get("dex", "")))
        if name == "unified_get_l2_book":
            return self.clients.unified.l2_book(
                str(args.get("coin", "BTC")),
                dex=str(args.get("dex", "")),
                depth=int(args["depth"]) if "depth" in args and args["depth"] is not None else None,
            )
        if name == "unified_get_asset_contexts":
            coin = str(args["coin"]) if "coin" in args and args["coin"] is not None else None
            return self.clients.unified.asset_contexts(coin=coin, dex=str(args.get("dex", "")))
        if name == "status_get_public":
            return self.clients.status.public_status()
        if name == "status_get_private":
            return self.clients.status.private_status()
        if name == "rpc_call":
            params = args.get("params", [])
            if not isinstance(params, list):
                raise RuntimeError("rpc_call params must be an array")
            return {
                "method": str(args.get("method", "")),
                "result": self.clients.api.rpc_call(str(args.get("method", "")), params=params),
            }
        raise KeyError(name)

    def handle_message(self, request: dict[str, Any]) -> dict[str, Any] | None:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        if not isinstance(method, str):
            return _jsonrpc_error(req_id, -32600, "Invalid Request")
        if method == "initialize":
            result = {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "serverInfo": {"name": "hypercore-python-mcp", "version": "0.3.1"},
                "capabilities": {"tools": {}},
            }
            return _jsonrpc_result(req_id, result)
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _jsonrpc_result(req_id, {"tools": self.tools})
        if method == "tools/call":
            tool_params = params if isinstance(params, dict) else {}
            name = tool_params.get("name")
            if not isinstance(name, str):
                return _jsonrpc_error(req_id, -32602, "Missing tool name")
            try:
                raw_arguments = tool_params.get("arguments")
                arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
                payload = self.call_tool(name, arguments)
            except KeyError:
                return _jsonrpc_error(req_id, -32601, f"Unknown tool: {name}")
            except Exception as exc:
                return _jsonrpc_error(req_id, -32000, str(exc))
            return _jsonrpc_result(req_id, _result_text(payload))
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    def run(self) -> None:
        try:
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                response: dict[str, Any] | None
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    response = _jsonrpc_error(None, -32700, "Parse error")
                else:
                    if not isinstance(request, dict):
                        response = _jsonrpc_error(None, -32600, "Invalid Request")
                    else:
                        response = self.handle_message(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
        finally:
            self.close()
