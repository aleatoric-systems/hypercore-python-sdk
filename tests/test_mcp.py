from __future__ import annotations

import io
import json

from hypercore_sdk.mcp import MCPClients, HypercoreMCPServer
from hypercore_sdk import mcp_cli


class _FakeAPI:
    def rpc_call(self, method: str, params=None, request_id: int = 1):
        return {"method": method, "params": params or [], "id": request_id}

    def close(self) -> None:
        return None


class _FakeGrpc:
    def get_mid_price(self, *, coin: str = "BTC"):
        return {"coin": coin, "price": 100.0}

    def stream_mids(self, **kwargs):
        return [{"coin": kwargs.get("coin", "BTC"), "channel": kwargs.get("subscription", "allMids")}]

    def get_block_number(self):
        return {"number": 42, "hex": "0x2a"}

    def stream_liquidations(self, **kwargs):
        return [{"symbol": kwargs.get("coin", "BTC"), "tx_hash": "0x1"}]


class _FakeUnified:
    def stats(self):
        return {"stats": {"latest_seq": 1}}

    def events(self, limit: int = 200, *, event_type=None, stream=None):
        return {"events": [{"limit": limit, "event_type": event_type, "stream": stream}]}

    def liquidation_cascades(self, limit: int = 200):
        return {"events": [{"limit": limit, "event_type": "liquidation_cascade", "stream": "liquidation_cascade"}]}

    def consensus_pulse(self):
        return {"consensus_pulse": {"current_block_height": 123}}

    def all_mids(self, *, dex: str = ""):
        return {"dex": dex, "snapshot": {"BTC": "60000"}}

    def l2_book(self, coin: str, *, dex: str = "", depth=None):
        return {"coin": coin, "dex": dex, "depth": depth}

    def asset_contexts(self, *, coin=None, dex: str = ""):
        return {"coin": coin, "dex": dex, "assets": [{"coin": coin or "BTC"}]}

    def close(self) -> None:
        return None


class _FakeStatus:
    def public_status(self):
        return {"snapshot": {"service": {"name": "public"}}}

    def private_status(self):
        return {"snapshot": {"service": {"name": "private"}}}

    def close(self) -> None:
        return None


def _payload(response: dict[str, object]) -> dict[str, object]:
    content = response["result"]["content"][0]["text"]  # type: ignore[index]
    return json.loads(content)


def _server() -> HypercoreMCPServer:
    return HypercoreMCPServer(
        clients=MCPClients(
            api=_FakeAPI(),
            grpc=_FakeGrpc(),
            unified=_FakeUnified(),
            status=_FakeStatus(),
        )
    )


def test_mcp_initialize_list_and_call() -> None:
    server = _server()

    init = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "unified_get_asset_contexts", "arguments": {"coin": "BTC"}},
        }
    )

    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "hypercore-python-mcp"
    assert tools is not None
    assert any(tool["name"] == "unified_get_l2_book" for tool in tools["result"]["tools"])
    assert any(tool["name"] == "unified_get_liquidation_cascades" for tool in tools["result"]["tools"])
    assert call is not None
    assert _payload(call)["assets"][0]["coin"] == "BTC"


def test_mcp_returns_error_for_unknown_tool() -> None:
    server = _server()
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32601


def test_mcp_covers_tool_matrix_and_error_paths() -> None:
    server = _server()
    for name, arguments, key in [
        ("catalog_interfaces", {}, "service_catalog"),
        ("grpc_get_mid_price", {"coin": "BTC"}, "coin"),
        ("grpc_stream_mids_sample", {"coin": "BTC", "subscription": "trades"}, "messages"),
        ("grpc_get_block_number", {}, "number"),
        ("grpc_stream_liquidations_sample", {"coin": "BTC"}, "messages"),
        ("unified_get_stats", {}, "stats"),
        ("unified_get_events", {"limit": 5, "event_type": "trade", "stream": "trades"}, "events"),
        ("unified_get_liquidation_cascades", {"limit": 5}, "events"),
        ("unified_get_consensus_pulse", {}, "consensus_pulse"),
        ("unified_get_all_mids", {}, "snapshot"),
        ("unified_get_l2_book", {"coin": "BTC", "depth": 5}, "coin"),
        ("unified_get_asset_contexts", {"coin": "BTC"}, "assets"),
        ("status_get_public", {}, "snapshot"),
        ("status_get_private", {}, "snapshot"),
        ("rpc_call", {"method": "eth_blockNumber", "params": []}, "result"),
    ]:
        response = server.handle_message(
            {"jsonrpc": "2.0", "id": name, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        )
        assert response is not None
        assert key in _payload(response)

    assert server.handle_message({"jsonrpc": "2.0", "id": 9, "method": "notifications/initialized"}) is None
    invalid = server.handle_message({"jsonrpc": "2.0", "id": 10, "method": 123})
    assert invalid is not None
    assert invalid["error"]["code"] == -32600
    missing = server.handle_message({"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {}})
    assert missing is not None
    assert missing["error"]["code"] == -32602
    bad_method = server.handle_message({"jsonrpc": "2.0", "id": 12, "method": "unknown/method"})
    assert bad_method is not None
    assert bad_method["error"]["code"] == -32601


def test_mcp_run_handles_parse_and_invalid_requests(monkeypatch) -> None:
    server = _server()
    stdin = io.StringIO("not-json\n[]\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("sys.stdout", stdout)
    server.run()
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["error"]["code"] == -32600
    assert "tools" in lines[2]["result"]


def test_mcp_cli_main(monkeypatch) -> None:
    seen: list[str] = []

    class _FakeServer:
        def run(self) -> None:
            seen.append("run")

    monkeypatch.setattr(mcp_cli, "HypercoreMCPServer", lambda: _FakeServer())
    assert mcp_cli.main() == 0
    assert seen == ["run"]
