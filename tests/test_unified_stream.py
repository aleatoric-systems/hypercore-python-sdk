from __future__ import annotations

from hypercore_sdk.config import SDKConfig
from hypercore_sdk.unified_stream import UnifiedStreamClient


class _FakeResponse:
    def __init__(self, body, *, lines=None) -> None:
        self._body = body
        self._lines = lines or []

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._body

    def iter_lines(self):
        for item in self._lines:
            yield item


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeClient:
    def __init__(self) -> None:
        self.get_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []
        self.responses: list[_FakeResponse] = []
        self.closed = False

    def get(self, url, headers=None, params=None):
        self.get_calls.append({"url": url, "headers": headers, "params": params})
        return self.responses.pop(0)

    def stream(self, method: str, url: str, headers=None, params=None):
        self.stream_calls.append({"method": method, "url": url, "headers": headers, "params": params})
        return _FakeStreamContext(self.responses.pop(0))

    def close(self) -> None:
        self.closed = True


def test_stats_and_events_use_expected_endpoints_and_headers() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse({"uptime_s": 100, "status": "ok"}),
        _FakeResponse({"events": [{"id": "evt-1"}]}),
        _FakeResponse({"events": [{"id": "evt-1"}]}),
        _FakeResponse({"events": [{"id": "evt-1"}]}),
        _FakeResponse({"consensus_pulse": {"current_block_height": 1}}),
        _FakeResponse({"snapshot": {"BTC": "60000"}, "count": 1}),
        _FakeResponse({"coin": "BTC", "levels": {"bids": [{"px": "60000"}], "asks": []}}),
        _FakeResponse({"assets": [{"coin": "BTC", "funding": "0.0001"}], "count": 1}),
    ]

    with UnifiedStreamClient(
        SDKConfig(
            unified_stream_url="https://stream.example",
            api_key="k",
        ),
        http_client=fake,
    ) as client:
        assert client.stats()["status"] == "ok"
        assert client.events(limit=50)["events"][0]["id"] == "evt-1"
        assert client.liquidations(limit=3)["events"][0]["id"] == "evt-1"
        assert client.liquidation_cascades(limit=4)["events"][0]["id"] == "evt-1"
        assert client.consensus_pulse()["consensus_pulse"]["current_block_height"] == 1
        assert client.all_mids()["snapshot"]["BTC"] == "60000"
        assert client.l2_book("BTC")["coin"] == "BTC"
        assert client.asset_contexts(coin="BTC")["assets"][0]["funding"] == "0.0001"

    assert fake.get_calls[0]["url"] == "https://stream.example/api/v1/unified/stats"
    assert fake.get_calls[1]["url"] == "https://stream.example/api/v1/unified/events"
    assert fake.get_calls[2]["url"] == "https://stream.example/api/v1/unified/events"
    assert fake.get_calls[2]["params"] == {"limit": 3, "event_type": "liquidation_warning"}
    assert fake.get_calls[3]["url"] == "https://stream.example/api/v1/unified/events"
    assert fake.get_calls[3]["params"] == {"limit": 4, "event_type": "liquidation_cascade"}
    assert fake.get_calls[4]["url"] == "https://stream.example/api/v1/unified/consensus-pulse"
    assert fake.get_calls[5]["url"] == "https://stream.example/api/v1/unified/all-mids"
    assert fake.get_calls[6]["url"] == "https://stream.example/api/v1/unified/l2-book"
    assert fake.get_calls[7]["url"] == "https://stream.example/api/v1/unified/asset-contexts"
    assert fake.get_calls[0]["headers"] == {"accept": "application/json", "x-api-key": "k"}
    assert fake.get_calls[1]["params"] == {"limit": 50}
    assert fake.get_calls[6]["params"] == {"coin": "BTC"}
    assert fake.get_calls[7]["params"] == {"coin": "BTC"}
    assert fake.closed is False


def test_events_limit_is_clamped_to_one() -> None:
    fake = _FakeClient()
    fake.responses = [_FakeResponse({"events": []})]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    client.events(limit=0)
    assert fake.get_calls[0]["params"] == {"limit": 1}


def test_events_supports_filters() -> None:
    fake = _FakeClient()
    fake.responses = [_FakeResponse({"events": []})]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    client.events(limit=5, event_type="trade", stream="trades")
    assert fake.get_calls[0]["params"] == {"limit": 5, "event_type": "trade", "stream": "trades"}


def test_sse_events_parses_data_lines_and_honors_max_events() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse(
            {},
            lines=[
                "",
                "event: ping",
                "data: {\"id\":1,\"kind\":\"block\"}",
                "data: {\"id\":2,\"kind\":\"fill\"}",
                "data: [1,2,3]",
            ],
        )
    ]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    items = list(client.sse_events(max_events=2))
    assert items == [{"id": 1, "kind": "block"}, {"id": 2, "kind": "fill"}]
    assert fake.stream_calls[0]["url"] == "https://stream.example/api/v1/unified/stream"


def test_specialized_sse_helpers_use_expected_endpoints() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse({}, lines=["data: {\"snapshot\":{\"BTC\":\"60000\"}}\n"]),
        _FakeResponse({}, lines=["data: {\"coin\":\"BTC\",\"levels\":{\"bids\":[],\"asks\":[]}}\n"]),
        _FakeResponse({}, lines=["data: {\"assets\":[{\"coin\":\"BTC\"}]}\n"]),
    ]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    assert list(client.sse_all_mids(max_events=1)) == [{"snapshot": {"BTC": "60000"}}]
    assert list(client.sse_l2_book("BTC", depth=1, max_events=1)) == [{"coin": "BTC", "levels": {"bids": [], "asks": []}}]
    assert list(client.sse_asset_contexts(coin="BTC", max_events=1)) == [{"assets": [{"coin": "BTC"}]}]
    assert fake.stream_calls[0]["url"] == "https://stream.example/api/v1/unified/all-mids/stream"
    assert fake.stream_calls[1]["url"] == "https://stream.example/api/v1/unified/l2-book/stream"
    assert fake.stream_calls[1]["params"] == {"coin": "BTC", "depth": 1}
    assert fake.stream_calls[2]["url"] == "https://stream.example/api/v1/unified/asset-contexts/stream"
    assert fake.stream_calls[2]["params"] == {"coin": "BTC"}


def test_unified_stream_rejects_non_object_payloads() -> None:
    fake = _FakeClient()
    fake.responses = [_FakeResponse([])]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    try:
        try:
            client.stats()
        except RuntimeError as exc:
            assert "Unexpected stats payload" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        client.close()


def test_unified_specialized_params_are_omitted_when_empty() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse({"snapshot": {"BTC": "60000"}}),
        _FakeResponse({"coin": "BTC", "levels": {"bids": [], "asks": []}}),
        _FakeResponse({"assets": []}),
        _FakeResponse({}, lines=["data: {\"snapshot\":{}}\n"]),
        _FakeResponse({}, lines=["data: {\"coin\":\"BTC\"}\n"]),
        _FakeResponse({}, lines=["data: {\"assets\":[]}\n"]),
    ]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    assert client.all_mids()["snapshot"] == {"BTC": "60000"}
    assert client.l2_book("BTC")["coin"] == "BTC"
    assert client.asset_contexts()["assets"] == []
    assert list(client.sse_all_mids(max_events=1)) == [{"snapshot": {}}]
    assert list(client.sse_l2_book("BTC", max_events=1)) == [{"coin": "BTC"}]
    assert list(client.sse_asset_contexts(max_events=1)) == [{"assets": []}]
    assert fake.get_calls[0]["params"] == {}
    assert fake.get_calls[1]["params"] == {"coin": "BTC"}
    assert fake.get_calls[2]["params"] == {}
    assert fake.stream_calls[0]["params"] == {}
    assert fake.stream_calls[1]["params"] == {"coin": "BTC"}
    assert fake.stream_calls[2]["params"] == {}


def test_owned_client_is_closed() -> None:
    cfg = SDKConfig(unified_stream_url="https://stream.example")
    client = UnifiedStreamClient(cfg)
    client.close()
