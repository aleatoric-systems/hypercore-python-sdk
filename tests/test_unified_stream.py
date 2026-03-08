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

    def stream(self, method: str, url: str, headers=None):
        self.stream_calls.append({"method": method, "url": url, "headers": headers})
        return _FakeStreamContext(self.responses.pop(0))

    def close(self) -> None:
        self.closed = True


def test_stats_and_events_use_expected_endpoints_and_headers() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse({"uptime_s": 100, "status": "ok"}),
        _FakeResponse({"events": [{"id": "evt-1"}]}),
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

    assert fake.get_calls[0]["url"] == "https://stream.example/api/v1/unified/stats"
    assert fake.get_calls[1]["url"] == "https://stream.example/api/v1/unified/events"
    assert fake.get_calls[0]["headers"] == {"accept": "application/json", "x-api-key": "k"}
    assert fake.get_calls[1]["params"] == {"limit": 50}
    assert fake.closed is False


def test_events_limit_is_clamped_to_one() -> None:
    fake = _FakeClient()
    fake.responses = [_FakeResponse({"events": []})]
    client = UnifiedStreamClient(SDKConfig(unified_stream_url="https://stream.example"), http_client=fake)
    client.events(limit=0)
    assert fake.get_calls[0]["params"] == {"limit": 1}


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


def test_owned_client_is_closed() -> None:
    cfg = SDKConfig(unified_stream_url="https://stream.example")
    client = UnifiedStreamClient(cfg)
    client.close()
