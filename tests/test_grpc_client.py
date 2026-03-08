from __future__ import annotations

import types

from hypercore_sdk import grpc_client
from hypercore_sdk.grpc_client import GrpcClient, GrpcConnectionConfig


class _DummyChannel:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_metadata_header() -> None:
    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", api_key="key-123"))
    assert client._metadata() == [("x-api-key", "key-123")]


def test_channel_uses_insecure_when_plaintext(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_insecure_channel(target: str, options):
        captured["target"] = target
        captured["options"] = options
        return _DummyChannel()

    monkeypatch.setattr(grpc_client.grpc, "insecure_channel", _fake_insecure_channel)

    client = GrpcClient(
        GrpcConnectionConfig(
            target="grpc.example:50051",
            use_tls=False,
            server_name="hl.grpc.example",
        )
    )
    channel = client._channel()

    assert isinstance(channel, _DummyChannel)
    assert captured["target"] == "grpc.example:50051"
    assert captured["options"] == [("grpc.ssl_target_name_override", "hl.grpc.example")]


def test_channel_uses_secure_with_credentials(monkeypatch, tmp_path) -> None:
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"TESTCERT")

    captured: dict[str, object] = {}

    def _fake_ssl_channel_credentials(root_certificates=None):
        captured["root_certificates"] = root_certificates
        return "creds"

    def _fake_secure_channel(target: str, creds, options):
        captured["target"] = target
        captured["creds"] = creds
        captured["options"] = options
        return _DummyChannel()

    monkeypatch.setattr(grpc_client.grpc, "ssl_channel_credentials", _fake_ssl_channel_credentials)
    monkeypatch.setattr(grpc_client.grpc, "secure_channel", _fake_secure_channel)

    client = GrpcClient(
        GrpcConnectionConfig(
            target="grpc.example:443",
            use_tls=True,
            server_name="hl.grpc.example",
            ca_cert_path=str(cert_path),
        )
    )
    channel = client._channel()

    assert isinstance(channel, _DummyChannel)
    assert captured["target"] == "grpc.example:443"
    assert captured["creds"] == "creds"
    assert captured["root_certificates"] == b"TESTCERT"
    assert captured["options"] == [("grpc.ssl_target_name_override", "hl.grpc.example")]


def test_grpcurl_invoke_builds_command(monkeypatch) -> None:
    def _fake_run(cmd, capture_output, text, check):
        assert capture_output is True
        assert text is True
        assert check is False
        return types.SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(grpc_client.subprocess, "run", _fake_run)

    client = GrpcClient(
        GrpcConnectionConfig(
            target="grpc.example:443",
            timeout_s=9.5,
            use_tls=True,
            server_name="hl.grpc.example",
            api_key="key-123",
            ca_cert_path="/tmp/ca.pem",
        )
    )
    result = client.grpcurl_invoke(
        method="hypercore.PriceService/GetMidPrice",
        request_json='{"coin":"BTC"}',
        proto="hypercore.proto",
        import_path="proto",
        insecure_tls=False,
    )

    command = result["command"]
    assert command[:3] == ["grpcurl", "-max-time", "9"]
    assert "-plaintext" not in command
    assert "-insecure" not in command
    assert "x-api-key: key-123" in command
    assert "hypercore.PriceService/GetMidPrice" in command
    assert result["returncode"] == 0


def test_grpcurl_invoke_handles_missing_binary(monkeypatch) -> None:
    def _fake_run(cmd, capture_output, text, check):
        raise FileNotFoundError("grpcurl not found")

    monkeypatch.setattr(grpc_client.subprocess, "run", _fake_run)

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443"))
    result = client.grpcurl_invoke(method="svc/Method")

    assert result["returncode"] == 127
    assert "grpcurl not found" in result["stderr"]


def test_health_check_success(monkeypatch) -> None:
    class _FakeHealthStub:
        def Check(self, request, timeout, metadata):
            return types.SimpleNamespace(status=grpc_client.health_pb2.HealthCheckResponse.SERVING)

    ticks = iter([10.0, 10.005])
    monkeypatch.setattr(grpc_client.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(grpc_client.health_pb2_grpc, "HealthStub", lambda channel: _FakeHealthStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    result = client.health_check(service="grpc.health.v1.Health")

    assert result["status"] == "SERVING"
    assert result["latency_ms"] == 5.0


def test_list_services_returns_sorted(monkeypatch) -> None:
    response = types.SimpleNamespace(
        list_services_response=types.SimpleNamespace(
            service=[types.SimpleNamespace(name="z.Service"), types.SimpleNamespace(name="a.Service")]
        )
    )

    class _FakeReflectionStub:
        def ServerReflectionInfo(self, requests, timeout, metadata):
            return iter([response])

    monkeypatch.setattr(grpc_client.reflection_pb2_grpc, "ServerReflectionStub", lambda channel: _FakeReflectionStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    assert client.list_services() == ["a.Service", "z.Service"]


def test_list_services_returns_empty_when_no_responses(monkeypatch) -> None:
    class _FakeReflectionStub:
        def ServerReflectionInfo(self, requests, timeout, metadata):
            return iter([])

    monkeypatch.setattr(grpc_client.reflection_pb2_grpc, "ServerReflectionStub", lambda channel: _FakeReflectionStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    assert client.list_services() == []


def test_health_speed_test_collects_errors(monkeypatch) -> None:
    calls = {"n": 0}

    def _fake_health_check(self, service=""):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return {"latency_ms": 3.0}

    monkeypatch.setattr(GrpcClient, "health_check", _fake_health_check)

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443"))
    result = client.health_speed_test(count=3, service="")

    assert result["ok"] == 2
    assert result["failed"] == 1
    assert result["stats"]["count"] == 2


def test_get_mid_price(monkeypatch) -> None:
    class _FakePriceStub:
        def GetMidPrice(self, request, timeout, metadata):
            return types.SimpleNamespace(
                coin="BTC",
                price=65000.5,
                ts_ms=1234567,
                source="ws",
                channel="allMids",
            )

    ticks = iter([1.0, 1.002])
    monkeypatch.setattr(grpc_client.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(grpc_client.bridge_pb2_grpc, "PriceServiceStub", lambda channel: _FakePriceStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    result = client.get_mid_price(coin="BTC")

    assert result["coin"] == "BTC"
    assert result["price"] == 65000.5
    assert result["latency_ms"] == 2.0


def test_get_block_number(monkeypatch) -> None:
    class _FakePriceStub:
        def GetBlockNumber(self, request, timeout, metadata):
            return types.SimpleNamespace(hex="0x10", number=16, ts_ms=987654)

    ticks = iter([2.0, 2.004])
    monkeypatch.setattr(grpc_client.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(grpc_client.bridge_pb2_grpc, "PriceServiceStub", lambda channel: _FakePriceStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    result = client.get_block_number()

    assert result["hex"] == "0x10"
    assert result["number"] == 16
    assert result["latency_ms"] == 4.0


def test_stream_mids_respects_max_messages(monkeypatch) -> None:
    items = [
        types.SimpleNamespace(coin="BTC", price=1.0, ts_ms=1, source="ws", channel="allMids"),
        types.SimpleNamespace(coin="BTC", price=2.0, ts_ms=2, source="ws", channel="allMids"),
        types.SimpleNamespace(coin="BTC", price=3.0, ts_ms=3, source="ws", channel="allMids"),
    ]

    class _FakePriceStub:
        def StreamMids(self, request, timeout, metadata):
            return iter(items)

    monkeypatch.setattr(grpc_client.bridge_pb2_grpc, "PriceServiceStub", lambda channel: _FakePriceStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    result = client.stream_mids(max_messages=2)

    assert len(result) == 2
    assert result[0]["price"] == 1.0
    assert result[1]["price"] == 2.0


def test_stream_liquidations_respects_max_messages(monkeypatch) -> None:
    items = [
        types.SimpleNamespace(
            symbol="BTC",
            tx_hash="0x1",
            block_number=1,
            log_index=0,
            ts_ms=1000,
            source="rpc",
            channel="liquidation_flash",
            address="0xabc",
            topic0="0xdeadbeef",
            data="0x00",
        ),
        types.SimpleNamespace(
            symbol="BTC",
            tx_hash="0x2",
            block_number=2,
            log_index=1,
            ts_ms=1001,
            source="rpc",
            channel="liquidation_flash",
            address="0xdef",
            topic0="0xdeadbeef",
            data="0x01",
        ),
    ]

    class _FakePriceStub:
        def StreamLiquidations(self, request, timeout, metadata):
            return iter(items)

    monkeypatch.setattr(grpc_client.bridge_pb2_grpc, "PriceServiceStub", lambda channel: _FakePriceStub())
    monkeypatch.setattr(GrpcClient, "_channel", lambda self: _DummyChannel())

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", timeout_s=2.0))
    result = client.stream_liquidations(max_messages=1)

    assert len(result) == 1
    assert result[0]["tx_hash"] == "0x1"
    assert result[0]["channel"] == "liquidation_flash"


def test_grpcurl_invoke_plaintext(monkeypatch) -> None:
    def _fake_run(cmd, capture_output, text, check):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(grpc_client.subprocess, "run", _fake_run)

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:50051", use_tls=False))
    result = client.grpcurl_invoke(method="svc/Method", request_json="{}")

    assert "-plaintext" in result["command"]


def test_grpcurl_invoke_insecure_tls(monkeypatch) -> None:
    def _fake_run(cmd, capture_output, text, check):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(grpc_client.subprocess, "run", _fake_run)

    client = GrpcClient(GrpcConnectionConfig(target="grpc.example:443", use_tls=True))
    result = client.grpcurl_invoke(method="svc/Method", request_json="{}", insecure_tls=True)

    assert "-insecure" in result["command"]
