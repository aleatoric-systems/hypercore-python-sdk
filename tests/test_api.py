from __future__ import annotations

import json

import pytest

from hypercore_sdk import api
from hypercore_sdk.api import HyperCoreAPI
from hypercore_sdk.config import SDKConfig


class _FakeResponse:
    def __init__(self, body, *, error: Exception | None = None) -> None:
        self._body = body
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse], calls: list[dict[str, object]]) -> None:
        self._responses = responses
        self._calls = calls
        self.closed = False

    def post(self, url, headers=None, content=None):
        self._calls.append({"url": url, "headers": headers, "content": content})
        if not self._responses:
            raise RuntimeError("No fake responses remaining")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, responses: list[_FakeResponse], calls: list[dict[str, object]], created: list[_FakeClient]) -> None:
    def _factory(timeout, verify, headers=None, limits=None):
        client = _FakeClient(responses, calls)
        created.append(client)
        return client

    monkeypatch.setattr(api.httpx, "Client", _factory)


def test_rpc_call_posts_jsonrpc_payload_and_reuses_client(monkeypatch) -> None:
    responses = [
        _FakeResponse({"jsonrpc": "2.0", "result": "0x2a", "id": 1}),
        _FakeResponse({"jsonrpc": "2.0", "result": "0x2b", "id": 1}),
    ]
    calls: list[dict[str, object]] = []
    created: list[_FakeClient] = []
    _patch_client(monkeypatch, responses, calls, created)

    client = HyperCoreAPI(SDKConfig(rpc_url="https://rpc.example", api_key="test-key", verify_tls=False))
    assert client.rpc_call("eth_blockNumber") == "0x2a"
    assert client.rpc_call("eth_blockNumber") == "0x2b"

    assert len(created) == 1
    assert len(calls) == 2
    payload = json.loads(str(calls[0]["content"]))
    assert payload == {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1,
    }
    assert calls[0]["headers"] == {
        "content-type": "application/json",
        "x-api-key": "test-key",
    }

    client.close()
    assert created[0].closed is True


def test_rpc_call_raises_on_rpc_error(monkeypatch) -> None:
    responses = [_FakeResponse({"error": {"code": -32000, "message": "boom"}})]
    calls: list[dict[str, object]] = []
    created: list[_FakeClient] = []
    _patch_client(monkeypatch, responses, calls, created)

    client = HyperCoreAPI(SDKConfig(rpc_url="https://rpc.example"))
    with pytest.raises(RuntimeError, match="RPC error"):
        client.rpc_call("eth_blockNumber")


def test_block_number_parses_hex(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "rpc_call", lambda self, method, params=None, request_id=1: "0x10")

    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    assert client.block_number() == 16


def test_block_number_raises_on_unexpected_payload(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "rpc_call", lambda self, method, params=None, request_id=1: 123)

    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    with pytest.raises(RuntimeError, match="Unexpected block number payload"):
        client.block_number()


def test_all_mids_and_coin_mid(monkeypatch) -> None:
    responses = [
        _FakeResponse({"BTC": "123.45", "ETH": 2222}),
        _FakeResponse({"BTC": "123.45", "ETH": 2222}),
    ]
    calls: list[dict[str, object]] = []
    created: list[_FakeClient] = []
    _patch_client(monkeypatch, responses, calls, created)

    client = HyperCoreAPI(SDKConfig(info_url="https://api.example/info", api_key="k"))
    mids = client.all_mids(dex="")
    assert mids == {"BTC": "123.45", "ETH": "2222"}
    assert client.coin_mid("BTC") == 123.45

    info_payload = json.loads(str(calls[0]["content"]))
    assert info_payload == {"type": "allMids", "dex": ""}
    assert calls[0]["headers"] == {
        "content-type": "application/json",
        "x-api-key": "k",
    }


def test_coin_mid_raises_when_coin_missing(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "all_mids", lambda self, dex="": {"BTC": "123"})
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))

    with pytest.raises(RuntimeError, match="Coin ETH not present"):
        client.coin_mid("ETH")


def test_meta_and_asset_ctxs_validation(monkeypatch) -> None:
    responses = [_FakeResponse({"bad": "shape"})]
    calls: list[dict[str, object]] = []
    created: list[_FakeClient] = []
    _patch_client(monkeypatch, responses, calls, created)

    client = HyperCoreAPI(SDKConfig())
    with pytest.raises(RuntimeError, match="Unexpected metaAndAssetCtxs payload"):
        client.meta_and_asset_ctxs()


def test_top_of_book_calculation(monkeypatch) -> None:
    monkeypatch.setattr(
        HyperCoreAPI,
        "l2_snapshot",
        lambda self, coin: {
            "coin": coin,
            "levels": [[{"px": "100.0", "sz": "1"}], [{"px": "101.0", "sz": "2"}]],
        },
    )
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))

    top = client.top_of_book("BTC")
    assert top["best_bid"] == 100.0
    assert top["best_ask"] == 101.0
    assert top["mid"] == 100.5
    assert top["spread"] == 1.0
    assert round(top["spread_bps"], 4) == round((1.0 / 100.5) * 10000, 4)


def test_asset_ctx_and_market_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "coin_mid", lambda self, coin, dex="": 65000.5)
    monkeypatch.setattr(HyperCoreAPI, "top_of_book", lambda self, coin: {"best_bid": 65000.0, "best_ask": 65001.0, "mid": 65000.5, "spread": 1.0, "spread_bps": 0.1538})
    monkeypatch.setattr(HyperCoreAPI, "orderbook_imbalance", lambda self, coin, depth=5: {"bid_notional": 1.0, "ask_notional": 0.9, "imbalance": 0.0526, "depth": float(depth)})
    monkeypatch.setattr(
        HyperCoreAPI,
        "meta_and_asset_ctxs",
        lambda self: (
            {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
            [{"funding": "0.0001", "openInterest": "1000"}, {"funding": "0.0002"}],
        ),
    )

    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    snapshot = client.market_snapshot("BTC")

    assert snapshot["coin"] == "BTC"
    assert snapshot["mid_px"] == 65000.5
    assert snapshot["orderbook_imbalance"]["imbalance"] == 0.0526
    assert snapshot["asset_ctx"]["funding"] == "0.0001"


def test_asset_ctx_raises_for_missing_coin(monkeypatch) -> None:
    monkeypatch.setattr(
        HyperCoreAPI,
        "meta_and_asset_ctxs",
        lambda self: ({"universe": [{"name": "ETH"}]}, [{"funding": "0.0002"}]),
    )
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))

    with pytest.raises(RuntimeError, match="Coin BTC not found"):
        client.asset_ctx("BTC")


def test_summarize_fills_and_user_flow_snapshot(monkeypatch) -> None:
    fills = [
        {"coin": "BTC", "px": "100", "sz": "0.5", "time": 1000},
        {"coin": "BTC", "px": "101", "sz": "0.25", "time": 1200},
        {"coin": "ETH", "px": "2000", "sz": "1.0", "time": 900},
    ]
    monkeypatch.setattr(HyperCoreAPI, "user_state", lambda self, address, dex="": {"withdrawable": "10"})
    monkeypatch.setattr(HyperCoreAPI, "open_orders", lambda self, address, dex="": [{"oid": 1}])
    monkeypatch.setattr(HyperCoreAPI, "user_fills", lambda self, address: fills)

    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    summary = client.summarize_fills(fills)
    assert summary["fills"] == 3
    assert summary["latest_fill_ms"] == 1200
    assert summary["by_coin"]["BTC"]["fills"] == 2

    user_flow = client.user_flow_snapshot("0xabc")
    assert user_flow["address"] == "0xabc"
    assert user_flow["fill_summary"]["fills"] == 3


def test_user_fills_by_time_payload(monkeypatch) -> None:
    responses = [_FakeResponse([{"coin": "BTC", "px": "100", "sz": "1", "time": 1000}])]
    calls: list[dict[str, object]] = []
    created: list[_FakeClient] = []
    _patch_client(monkeypatch, responses, calls, created)

    client = HyperCoreAPI(SDKConfig(info_url="https://api.example/info"))
    fills = client.user_fills_by_time("0xabc", start_time_ms=1, end_time_ms=10, aggregate_by_time=True)

    assert len(fills) == 1
    payload = json.loads(str(calls[0]["content"]))
    assert payload == {
        "type": "userFillsByTime",
        "user": "0xabc",
        "startTime": 1,
        "aggregateByTime": True,
        "endTime": 10,
    }


def test_context_manager_and_non_owned_client_close_behavior() -> None:
    injected = _FakeClient([], [])
    api_client = HyperCoreAPI(SDKConfig(), http_client=injected)
    with api_client as entered:
        assert entered is api_client
    # Injected clients are caller-managed.
    assert injected.closed is False


def test_rpc_call_rejects_non_dict_payload(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "_post_json", lambda self, url, payload, headers=None: [1, 2, 3])
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    with pytest.raises(RuntimeError, match="Unexpected RPC response payload"):
        client.rpc_call("eth_blockNumber")


def test_info_surface_wrappers_roundtrip(monkeypatch) -> None:
    def _fake_info_call(self, info_type: str, **kwargs):
        mapping = {
            "meta": {"universe": [{"name": "BTC"}]},
            "spotMeta": {"universe": [], "tokens": []},
            "metaAndAssetCtxs": [{"universe": [{"name": "BTC"}]}, [{"funding": "0.0001"}]],
            "spotMetaAndAssetCtxs": [{"universe": [], "tokens": []}, [{"coin": "PURR"}]],
            "l2Book": {"coin": kwargs.get("coin", ""), "levels": []},
            "candleSnapshot": [{"t": 1}, "drop-me"],
            "fundingHistory": [{"coin": kwargs.get("coin", "")}],
            "clearinghouseState": {"user": kwargs.get("user", "")},
            "spotClearinghouseState": {"user": kwargs.get("user", "")},
            "openOrders": [{"oid": 1}],
            "frontendOpenOrders": [{"oid": 2}],
            "userFills": [{"coin": "BTC"}],
            "portfolio": {"portfolio": True},
            "userNonFundingLedgerUpdates": [{"delta": 1}],
            "historicalOrders": [{"oid": 3}],
            "userTwapSliceFills": [{"slice": 1}],
            "userVaultEquities": [{"vault": "x"}],
            "userRole": {"role": "user"},
            "userRateLimit": {"limit": 1000},
        }
        return mapping[info_type]

    monkeypatch.setattr(HyperCoreAPI, "info_call", _fake_info_call)

    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))

    assert client.meta()["universe"][0]["name"] == "BTC"
    assert "tokens" in client.spot_meta()
    assert client.meta_and_asset_ctxs()[1][0]["funding"] == "0.0001"
    assert client.spot_meta_and_asset_ctxs()[1][0]["coin"] == "PURR"
    assert client.l2_snapshot("BTC")["coin"] == "BTC"
    assert len(client.candles_snapshot("BTC", "1m", 1, 2)) == 1
    assert client.funding_history("BTC", 1)[0]["coin"] == "BTC"
    assert client.user_state("0xabc")["user"] == "0xabc"
    assert client.spot_user_state("0xabc")["user"] == "0xabc"
    assert client.open_orders("0xabc")[0]["oid"] == 1
    assert client.frontend_open_orders("0xabc")[0]["oid"] == 2
    assert client.user_fills("0xabc")[0]["coin"] == "BTC"
    assert client.portfolio("0xabc")["portfolio"] is True
    assert client.user_non_funding_ledger_updates("0xabc", 1)[0]["delta"] == 1
    assert client.historical_orders("0xabc")[0]["oid"] == 3
    assert client.user_twap_slice_fills("0xabc")[0]["slice"] == 1
    assert client.user_vault_equities("0xabc")[0]["vault"] == "x"
    assert client.user_role("0xabc")["role"] == "user"
    assert client.user_rate_limit("0xabc")["limit"] == 1000


def test_top_of_book_raises_on_bad_levels(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "l2_snapshot", lambda self, coin: {"coin": coin, "levels": []})
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    with pytest.raises(RuntimeError, match="Unexpected l2Book level structure"):
        client.top_of_book("BTC")


def test_asset_ctx_raises_on_bad_universe_shape(monkeypatch) -> None:
    monkeypatch.setattr(HyperCoreAPI, "meta_and_asset_ctxs", lambda self: ({"universe": {}}, []))
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    with pytest.raises(RuntimeError, match="Unexpected meta universe payload"):
        client.asset_ctx("BTC")


def test_orderbook_imbalance_calculation(monkeypatch) -> None:
    monkeypatch.setattr(
        HyperCoreAPI,
        "l2_snapshot",
        lambda self, coin: {
            "coin": coin,
            "levels": [
                [{"px": "100", "sz": "1"}, {"px": "99", "sz": "2"}],
                [{"px": "101", "sz": "1.5"}, {"px": "102", "sz": "1"}],
            ],
        },
    )
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    out = client.orderbook_imbalance("BTC", depth=2)
    assert round(out["bid_notional"], 4) == 298.0
    assert round(out["ask_notional"], 4) == 253.5
    assert out["depth"] == 2.0


def test_summarize_funding_history_and_snapshot(monkeypatch) -> None:
    rows = [
        {"fundingRate": "0.0001", "time": 1},
        {"fundingRate": "-0.0002", "time": 2},
        {"fundingRate": "0.0003", "time": 3},
    ]
    summary = HyperCoreAPI.summarize_funding_history(rows)
    assert summary["count"] == 3
    assert summary["latest_time_ms"] == 3
    assert round(summary["avg_funding_rate"], 10) == round((0.0001 - 0.0002 + 0.0003) / 3.0, 10)
    assert HyperCoreAPI.summarize_funding_history([])["count"] == 0

    monkeypatch.setattr(HyperCoreAPI, "funding_history", lambda self, coin, start_time_ms, end_time_ms=None: rows)
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    snapshot = client.funding_snapshot("BTC", start_time_ms=10, end_time_ms=20)
    assert snapshot["coin"] == "BTC"
    assert snapshot["summary"]["count"] == 3


def test_summarize_non_funding_ledger_updates_and_activity_snapshot(monkeypatch) -> None:
    updates = [
        {"type": "deposit", "time": 10},
        {"type": "withdrawal", "time": 11},
        {"type": "deposit", "time": 12},
    ]
    summary = HyperCoreAPI.summarize_non_funding_ledger_updates(updates)
    assert summary["count"] == 3
    assert summary["by_type"]["deposit"] == 2
    assert summary["latest_time_ms"] == 12

    monkeypatch.setattr(HyperCoreAPI, "user_fills_by_time", lambda self, address, start_time_ms, end_time_ms=None, aggregate_by_time=False: [{"coin": "BTC", "px": "100", "sz": "0.1", "time": 50}])
    monkeypatch.setattr(HyperCoreAPI, "user_non_funding_ledger_updates", lambda self, address, start_time_ms, end_time_ms=None: updates)
    monkeypatch.setattr(HyperCoreAPI, "user_state", lambda self, address, dex="": {"withdrawable": "5"})
    client = HyperCoreAPI(SDKConfig(), http_client=_FakeClient([], []))
    out = client.user_activity_snapshot("0xabc", start_time_ms=1, end_time_ms=2)
    assert out["fills_summary"]["fills"] == 1
    assert out["ledger_summary"]["by_type"]["deposit"] == 2
