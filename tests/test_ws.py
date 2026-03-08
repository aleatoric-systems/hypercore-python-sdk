from __future__ import annotations

import json

import pytest

from hypercore_sdk import ws
from hypercore_sdk.ws import _extract_price, get_price_from_ws


@pytest.mark.parametrize(
    ("channel", "payload", "coin", "expected"),
    [
        (
            "allMids",
            {"data": {"mids": {"BTC": "101.2"}}},
            "BTC",
            101.2,
        ),
        (
            "trades",
            {"data": [{"coin": "BTC", "px": "102.3"}]},
            "BTC",
            102.3,
        ),
        (
            "l2Book",
            {
                "data": {
                    "coin": "BTC",
                    "levels": [
                        [{"px": "100.0"}],
                        [{"px": "102.0"}],
                    ],
                }
            },
            "BTC",
            101.0,
        ),
    ],
)
def test_extract_price(channel: str, payload: dict[str, object], coin: str, expected: float) -> None:
    assert _extract_price(channel, payload, coin) == expected


def test_extract_price_none_for_unrecognized_shape() -> None:
    assert _extract_price("trades", {"data": []}, "BTC") is None


class _FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = messages
        self.sent_messages: list[str] = []

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def recv(self) -> str:
        if not self._messages:
            raise RuntimeError("No more websocket messages")
        return self._messages.pop(0)


class _FakeConnection:
    def __init__(self, ws_obj: _FakeWebSocket) -> None:
        self._ws = ws_obj

    async def __aenter__(self) -> _FakeWebSocket:
        return self._ws

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_get_price_from_ws_subscribes_and_returns_first_price(monkeypatch) -> None:
    frames = [
        json.dumps({"channel": "subscriptionResponse", "data": {}}),
        json.dumps({"channel": "allMids", "data": {"mids": {"BTC": "65432.1"}}}),
    ]
    fake_ws = _FakeWebSocket(frames)
    captured: dict[str, object] = {}

    def _fake_connect(url: str, additional_headers: dict[str, str], max_size: int | None = None):
        captured["url"] = url
        captured["headers"] = additional_headers
        captured["max_size"] = max_size
        return _FakeConnection(fake_ws)

    monkeypatch.setattr(ws.websockets, "connect", _fake_connect)

    result = await get_price_from_ws(
        ws_url="wss://example/ws",
        coin="BTC",
        subscription_type="allMids",
        timeout_s=2.0,
        api_key="key-123",
    )

    assert result["coin"] == "BTC"
    assert result["price"] == 65432.1
    assert result["channel"] == "allMids"
    assert isinstance(result["latency_ms"], float)

    assert captured["url"] == "wss://example/ws"
    assert captured["headers"] == {"x-api-key": "key-123"}
    assert captured["max_size"] is None

    assert len(fake_ws.sent_messages) == 1
    sent_payload = json.loads(fake_ws.sent_messages[0])
    assert sent_payload == {
        "method": "subscribe",
        "subscription": {"type": "allMids"},
    }


@pytest.mark.asyncio
async def test_get_price_from_ws_trades_subscription_includes_coin(monkeypatch) -> None:
    frames = [
        json.dumps({"channel": "pong", "data": {}}),
        json.dumps({"channel": "trades", "data": [{"coin": "ETH", "px": "10.0"}]}),
        json.dumps({"channel": "trades", "data": [{"coin": "BTC", "px": "11.5"}]}),
    ]
    fake_ws = _FakeWebSocket(frames)

    def _fake_connect(url: str, additional_headers: dict[str, str], max_size: int | None = None):
        return _FakeConnection(fake_ws)

    monkeypatch.setattr(ws.websockets, "connect", _fake_connect)

    result = await get_price_from_ws(
        ws_url="wss://example/ws",
        coin="BTC",
        subscription_type="trades",
        timeout_s=2.0,
    )

    assert result["price"] == 11.5
    sent_payload = json.loads(fake_ws.sent_messages[0])
    assert sent_payload["subscription"] == {"type": "trades", "coin": "BTC"}


@pytest.mark.asyncio
async def test_get_price_from_ws_passes_max_size(monkeypatch) -> None:
    frames = [json.dumps({"channel": "allMids", "data": {"mids": {"BTC": "65000.0"}}})]
    fake_ws = _FakeWebSocket(frames)
    captured: dict[str, object] = {}

    def _fake_connect(url: str, additional_headers: dict[str, str], max_size: int | None = None):
        captured["max_size"] = max_size
        return _FakeConnection(fake_ws)

    monkeypatch.setattr(ws.websockets, "connect", _fake_connect)

    await get_price_from_ws(
        ws_url="wss://example/ws",
        coin="BTC",
        subscription_type="allMids",
        timeout_s=2.0,
        max_message_bytes=8 * 1024 * 1024,
    )

    assert captured["max_size"] == 8 * 1024 * 1024
