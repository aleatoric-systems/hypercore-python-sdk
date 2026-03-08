from __future__ import annotations

import json

import pytest

from hypercore_sdk import cli


class _FakeApi:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def __enter__(self) -> "_FakeApi":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def rpc_call(self, method: str, params=None, request_id: int = 1):
        return {"method": method, "params": params, "id": request_id}

    def coin_mid(self, coin: str) -> float:
        return 123.45

    def market_snapshot(self, coin: str):
        return {"coin": coin, "mid_px": 123.45, "top_of_book": {"best_bid": 123.4, "best_ask": 123.5}, "asset_ctx": {"funding": "0.0001"}}

    def user_flow_snapshot(self, address: str, dex: str = ""):
        return {"address": address, "user_state": {"withdrawable": "1"}, "open_orders": [], "fill_summary": {"fills": 0}}

    def user_fills(self, address: str):
        return [{"coin": "BTC", "px": "100", "sz": "0.1", "time": 10}]

    def user_fills_by_time(self, address: str, start_time_ms: int, end_time_ms: int | None = None, aggregate_by_time: bool = False):
        return [{"coin": "BTC", "px": "101", "sz": "0.2", "time": 20}]

    def summarize_fills(self, fills):
        return {"fills": len(fills)}

    def funding_snapshot(self, coin: str, start_time_ms: int, end_time_ms: int | None = None):
        return {"coin": coin, "window": {"start_time_ms": start_time_ms, "end_time_ms": end_time_ms}, "summary": {"count": 2}, "rows": []}

    def user_activity_snapshot(self, address: str, start_time_ms: int, end_time_ms: int | None = None, dex: str = ""):
        return {"address": address, "window": {"start_time_ms": start_time_ms, "end_time_ms": end_time_ms}, "fills_summary": {"fills": 1}, "ledger_summary": {"count": 1}}


class _FakeUnifiedStreamClient:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def __enter__(self) -> "_FakeUnifiedStreamClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def stats(self):
        return {"uptime_s": 1234, "status": "ok"}

    def events(self, limit: int = 200):
        return {"events": [{"id": "evt-1"}], "limit": limit}

    def sse_events(self, max_events: int = 20):
        for idx in range(max_events):
            yield {"id": idx}


class _FakeGrpcClient:
    invoke_returncode = 0

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def health_check(self, service: str = ""):
        return {"status": "SERVING", "service": service}

    def list_services(self):
        return ["svc.A", "svc.B"]

    def grpcurl_invoke(self, **kwargs):
        return {"returncode": self.invoke_returncode, **kwargs}

    def get_mid_price(self, coin: str = "BTC"):
        return {"coin": coin, "price": 123.4}

    def stream_mids(self, **kwargs):
        return [{"coin": "BTC", "price": 1.0}]

    def stream_liquidations(self, **kwargs):
        return [{"symbol": "BTC", "tx_hash": "0x1", "channel": "liquidation_flash"}]

    def get_block_number(self):
        return {"number": 42, "hex": "0x2a"}


def test_cli_rpc_call_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "HyperCoreAPI", _FakeApi)

    code = cli.main(
        [
            "rpc",
            "call",
            "--method",
            "eth_blockNumber",
            "--params",
            "[]",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "eth_blockNumber"
    assert payload["result"]["params"] == []


def test_cli_rpc_call_rejects_non_array_params(capsys) -> None:
    code = cli.main(
        [
            "rpc",
            "call",
            "--method",
            "eth_blockNumber",
            "--params",
            '{"not":"array"}',
        ]
    )

    assert code == 2
    assert "--params must be a JSON array" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected_key"),
    [
        (["stream", "stats"], "status"),
        (["stream", "events", "--limit", "3"], "events"),
        (["stream", "sse", "--max-events", "2"], "events"),
    ],
)
def test_cli_stream_commands(monkeypatch, capsys, argv: list[str], expected_key: str) -> None:
    monkeypatch.setattr(cli, "UnifiedStreamClient", _FakeUnifiedStreamClient)
    code = cli.main(argv)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert expected_key in payload


def test_cli_grpc_template_output(capsys) -> None:
    code = cli.main(
        [
            "grpc",
            "setup-template",
            "--server-name",
            "hl.grpc.example.com",
            "--upstream",
            "127.0.0.1:50051",
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "server_name hl.grpc.example.com;" in output
    assert "grpc_pass grpc://127.0.0.1:50051;" in output


def test_cli_price_ws_projection(monkeypatch, capsys) -> None:
    async def _fake_get_price_from_ws(**kwargs):
        return {
            "coin": "BTC",
            "price": 100.0,
            "channel": "allMids",
            "latency_ms": 1.2,
            "message": {"raw": True},
        }

    monkeypatch.setattr(cli, "get_price_from_ws", _fake_get_price_from_ws)
    code = cli.main(["price", "ws", "--ws-url", "wss://x"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "coin": "BTC",
        "price": 100.0,
        "channel": "allMids",
        "latency_ms": 1.2,
    }


def test_cli_price_ws_raw_message(monkeypatch, capsys) -> None:
    async def _fake_get_price_from_ws(**kwargs):
        return {"coin": "BTC", "price": 100.0, "channel": "allMids", "latency_ms": 1.2, "message": {"x": 1}}

    monkeypatch.setattr(cli, "get_price_from_ws", _fake_get_price_from_ws)
    code = cli.main(["price", "ws", "--ws-url", "wss://x", "--raw-message"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["message"] == {"x": 1}


def test_cli_price_info(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "HyperCoreAPI", _FakeApi)
    code = cli.main(["price", "info", "--coin", "ETH"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["coin"] == "ETH"
    assert payload["price"] == 123.45


@pytest.mark.parametrize(
    ("argv", "expected_key"),
    [
        (["intel", "market", "--coin", "BTC"], "asset_ctx"),
        (["intel", "user-flow", "--address", "0xabc"], "fill_summary"),
        (["intel", "fills", "--address", "0xabc"], "summary"),
        (["intel", "fills", "--address", "0xabc", "--start-time-ms", "1", "--end-time-ms", "2", "--aggregate-by-time"], "fills"),
        (["intel", "funding", "--coin", "BTC", "--start-time-ms", "1", "--end-time-ms", "2"], "summary"),
        (["intel", "activity", "--address", "0xabc", "--start-time-ms", "1", "--end-time-ms", "2"], "ledger_summary"),
    ],
)
def test_cli_intel_commands(monkeypatch, capsys, argv: list[str], expected_key: str) -> None:
    monkeypatch.setattr(cli, "HyperCoreAPI", _FakeApi)
    code = cli.main(argv)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert expected_key in payload


@pytest.mark.parametrize(
    ("argv", "expected_key"),
    [
        (["grpc", "health"], "status"),
        (["grpc", "list-services"], "services"),
        (["grpc", "price", "--coin", "BTC"], "coin"),
        (["grpc", "stream"], "messages"),
        (["grpc", "liquidations"], "messages"),
        (["grpc", "block-number"], "number"),
    ],
)
def test_cli_grpc_commands(monkeypatch, capsys, argv: list[str], expected_key: str) -> None:
    monkeypatch.setattr(cli, "GrpcClient", _FakeGrpcClient)
    code = cli.main(argv)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert expected_key in payload


def test_cli_grpc_invoke_non_zero_exit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "GrpcClient", _FakeGrpcClient)
    _FakeGrpcClient.invoke_returncode = 1
    code = cli.main(["grpc", "invoke", "--method", "svc/Method"])
    _FakeGrpcClient.invoke_returncode = 0

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["returncode"] == 1


def test_cli_speed_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "HyperCoreAPI", _FakeApi)
    monkeypatch.setattr(cli, "GrpcClient", _FakeGrpcClient)
    monkeypatch.setattr(cli, "run_rpc_speed_test", lambda api, count: {"ok": count, "kind": "rpc"})
    monkeypatch.setattr(
        cli,
        "run_ws_speed_test",
        lambda **kwargs: {"ok": kwargs["count"], "kind": "ws", "subscription": kwargs["subscription_type"]},
    )
    monkeypatch.setattr(cli, "run_grpc_health_speed_test", lambda client, count, service: {"ok": count, "kind": "grpc"})

    assert cli.main(["speed", "rpc", "--count", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "rpc"

    assert cli.main(["speed", "ws", "--count", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["subscription"] == "allMids"

    assert cli.main(["speed", "grpc-health", "--count", "4"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "grpc"
