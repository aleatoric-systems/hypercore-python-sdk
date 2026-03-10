from __future__ import annotations

import importlib.util
import sys
import types
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "grpc_l2book_trades_console.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("examples.grpc_l2book_trades_console", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_event_payload_computes_latency(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.time, "time", lambda: 2.5)

    item = types.SimpleNamespace(
        coin="BTC",
        price=90123.45,
        ts_ms=1000,
        source="bridge",
        channel="l2Book",
    )

    event = module._event_payload(item, subscription="l2Book")

    assert event.subscription == "l2Book"
    assert event.coin == "BTC"
    assert event.price == 90123.45
    assert event.received_at_ms == 2500
    assert event.ingest_latency_ms == 1500.0


def test_price_delta_bps_handles_missing_values() -> None:
    module = _load_module()

    assert module._price_delta_bps(100.10, 100.0) == 10.0
    assert module._price_delta_bps(None, 100.0) is None
    assert module._price_delta_bps(100.0, None) is None
    assert module._price_delta_bps(100.0, 0.0) is None


def test_render_screen_includes_snapshots_history_and_errors(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.time, "time", lambda: 200.0)

    states = {
        subscription: module.FeedState(subscription=subscription) for subscription in module.SUBSCRIPTIONS
    }
    states["l2Book"].latest = module.FeedUpdate(
        subscription="l2Book",
        coin="BTC",
        price=100.2,
        ts_ms=198000,
        source="bridge",
        channel="l2Book",
        received_at_ms=199500,
        ingest_latency_ms=2000.0,
    )
    states["l2Book"].updates = 4
    states["trades"].latest = module.FeedUpdate(
        subscription="trades",
        coin="BTC",
        price=100.0,
        ts_ms=198100,
        source="bridge",
        channel="trades",
        received_at_ms=199600,
        ingest_latency_ms=1900.0,
    )
    states["trades"].updates = 7
    states["trades"].error = "StatusCode.UNAVAILABLE upstream reset"

    history = deque(
        [
            states["l2Book"].latest,
            states["trades"].latest,
        ],
        maxlen=5,
    )

    screen = module._render_screen(
        coin="BTC",
        target="grpc.example:443",
        heartbeat_s=10,
        preflight=module.AuthPreflight(
            key_source="GRPC_STREAM_KEY",
            key_present=True,
            health_status="SERVING",
            health_latency_ms=12.3,
        ),
        started_at=190.0,
        states=states,
        history=history,
        total_events=11,
    )

    assert "Hypercore gRPC live feeds | coin=BTC | uptime=10.0s" in screen
    assert "target=grpc.example:443 | heartbeat=10s | events=11" in screen
    assert "key_source=GRPC_STREAM_KEY | key_present=yes" in screen
    assert "health=SERVING | health_latency_ms=12.3" in screen
    assert "l2Book vs trades delta: +20.00 bps" in screen
    assert "Recent updates (newest first)" in screen
    assert "Errors" in screen
    assert "trades: StatusCode.UNAVAILABLE upstream reset" in screen


def test_resolve_api_key_reports_source(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("GRPC_STREAM_KEY", "grpc_key")
    monkeypatch.delenv("ALEATORIC_GRPC_KEY", raising=False)
    monkeypatch.delenv("UNIFIED_STREAM_KEY", raising=False)
    monkeypatch.delenv("UNIFIED_KEY", raising=False)
    monkeypatch.delenv("RPC_GATEWAY_KEY", raising=False)
    monkeypatch.delenv("RPC_KEY", raising=False)
    monkeypatch.delenv("HYPER_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("api_keys", raising=False)

    cfg = module.SDKConfig(api_key=None)
    api_key, source = module._resolve_api_key(None, cfg)

    assert api_key == "grpc_key"
    assert source == "GRPC_STREAM_KEY"


def test_resolve_api_key_prefers_rpc_gateway_key_over_grpc_stream_key(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("GRPC_STREAM_KEY", "grpc_key")
    monkeypatch.setenv("RPC_GATEWAY_KEY", "rpc_key")
    monkeypatch.delenv("ALEATORIC_GRPC_KEY", raising=False)
    monkeypatch.delenv("UNIFIED_STREAM_KEY", raising=False)
    monkeypatch.delenv("UNIFIED_KEY", raising=False)
    monkeypatch.delenv("RPC_KEY", raising=False)
    monkeypatch.delenv("HYPER_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("api_keys", raising=False)

    cfg = module.SDKConfig(api_key=None)
    api_key, source = module._resolve_api_key(None, cfg)

    assert api_key == "rpc_key"
    assert source == "RPC_GATEWAY_KEY"


def test_detect_auth_diagnosis_when_health_works() -> None:
    module = _load_module()
    states = {
        subscription: module.FeedState(subscription=subscription) for subscription in module.SUBSCRIPTIONS
    }
    states["l2Book"].error = "StatusCode.PERMISSION_DENIED Received http2 header with status: 403"
    states["trades"].error = "StatusCode.PERMISSION_DENIED Received http2 header with status: 403"

    diagnosis = module._detect_auth_diagnosis(
        states,
        module.AuthPreflight(
            key_source="GRPC_STREAM_KEY",
            key_present=True,
            health_status="SERVING",
            health_latency_ms=9.4,
        ),
        total_events=0,
    )

    assert diagnosis == "health works, stream auth denied by endpoint; selected key source: GRPC_STREAM_KEY"


def test_detect_auth_diagnosis_when_health_and_streams_denied() -> None:
    module = _load_module()
    states = {
        subscription: module.FeedState(subscription=subscription) for subscription in module.SUBSCRIPTIONS
    }
    states["l2Book"].error = "StatusCode.PERMISSION_DENIED Received http2 header with status: 403"
    states["trades"].error = "StatusCode.PERMISSION_DENIED Received http2 header with status: 403"

    diagnosis = module._detect_auth_diagnosis(
        states,
        module.AuthPreflight(
            key_source="GRPC_STREAM_KEY",
            key_present=True,
            health_error_code="StatusCode.PERMISSION_DENIED",
            health_error="Received http2 header with status: 403",
        ),
        total_events=0,
    )

    assert diagnosis == "health and stream auth denied by endpoint; selected key source: GRPC_STREAM_KEY"
