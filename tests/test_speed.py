from __future__ import annotations

from hypercore_sdk import speed
from hypercore_sdk.speed import run_grpc_health_speed_test, run_rpc_speed_test, run_ws_speed_test


class _DummyAPI:
    def __init__(self) -> None:
        self.calls = 0

    def block_number(self) -> int:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("temporary rpc failure")
        return 42


def test_run_rpc_speed_test_collects_success_and_failures() -> None:
    result = run_rpc_speed_test(_DummyAPI(), count=3)
    assert result["ok"] == 2
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert result["stats"]["count"] == 2


def test_run_ws_speed_test_collects_latencies(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    async def _fake_get_price_from_ws(**kwargs):
        captured.append(kwargs)
        return {"latency_ms": 12.5}

    monkeypatch.setattr(speed, "get_price_from_ws", _fake_get_price_from_ws)

    result = run_ws_speed_test(ws_url="wss://example/ws", count=2, max_message_bytes=None)
    assert result["ok"] == 2
    assert result["failed"] == 0
    assert result["stats"]["count"] == 2
    assert len(captured) == 2
    assert all("max_message_bytes" in call for call in captured)


def test_run_ws_speed_test_collects_errors(monkeypatch) -> None:
    async def _failing_get_price_from_ws(**kwargs):
        raise RuntimeError("ws failure")

    monkeypatch.setattr(speed, "get_price_from_ws", _failing_get_price_from_ws)

    result = run_ws_speed_test(ws_url="wss://example/ws", count=2)
    assert result["ok"] == 0
    assert result["failed"] == 2


class _DummyGrpcClient:
    def health_speed_test(self, *, count: int, service: str):
        return {
            "ok": count,
            "failed": 0,
            "errors": [],
            "stats": {"count": count},
            "service": service,
        }


def test_run_grpc_health_speed_test_delegates() -> None:
    result = run_grpc_health_speed_test(_DummyGrpcClient(), count=5, service="grpc.health.v1.Health")
    assert result["ok"] == 5
    assert result["service"] == "grpc.health.v1.Health"
