from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from .proto import hypercore_bridge_pb2 as bridge_pb2
from .proto import hypercore_bridge_pb2_grpc as bridge_pb2_grpc
from .stats import summarize_latencies


@dataclass(slots=True)
class GrpcConnectionConfig:
    target: str
    timeout_s: float = 5.0
    use_tls: bool = True
    server_name: str | None = None
    api_key: str | None = None
    ca_cert_path: str | None = None


class GrpcClient:
    def __init__(self, cfg: GrpcConnectionConfig):
        self.cfg = cfg

    def _metadata(self) -> list[tuple[str, str]] | None:
        if not self.cfg.api_key:
            return None
        return [("x-api-key", self.cfg.api_key)]

    def _channel(self) -> grpc.Channel:
        options: list[tuple[str, Any]] = []
        if self.cfg.server_name:
            options.append(("grpc.ssl_target_name_override", self.cfg.server_name))
        if self.cfg.use_tls:
            root_certificates = None
            if self.cfg.ca_cert_path:
                with open(self.cfg.ca_cert_path, "rb") as f:
                    root_certificates = f.read()
            creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
            return grpc.secure_channel(self.cfg.target, creds, options=options)
        return grpc.insecure_channel(self.cfg.target, options=options)

    def health_check(self, service: str = "") -> dict[str, Any]:
        with self._channel() as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            start = time.perf_counter()
            response = stub.Check(
                health_pb2.HealthCheckRequest(service=service),
                timeout=self.cfg.timeout_s,
                metadata=self._metadata(),
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "status": health_pb2.HealthCheckResponse.ServingStatus.Name(response.status),
                "latency_ms": round(elapsed_ms, 3),
            }

    def list_services(self) -> list[str]:
        request = reflection_pb2.ServerReflectionRequest(list_services="")
        with self._channel() as channel:
            stub = reflection_pb2_grpc.ServerReflectionStub(channel)
            responses = stub.ServerReflectionInfo(
                iter([request]),
                timeout=self.cfg.timeout_s,
                metadata=self._metadata(),
            )
            for response in responses:
                service_list = response.list_services_response.service
                return sorted(service.name for service in service_list)
        return []

    def health_speed_test(self, *, count: int = 20, service: str = "") -> dict[str, Any]:
        latencies: list[float] = []
        errors: list[str] = []
        for _ in range(count):
            try:
                result = self.health_check(service=service)
                latencies.append(float(result["latency_ms"]))
            except Exception as exc:  # pragma: no cover - network failures vary
                errors.append(str(exc))
        return {
            "stats": summarize_latencies(latencies).as_dict(),
            "ok": len(latencies),
            "failed": len(errors),
            "errors": errors[:5],
        }

    def get_mid_price(self, *, coin: str = "BTC") -> dict[str, Any]:
        request = bridge_pb2.MidPriceRequest(coin=coin)
        with self._channel() as channel:
            stub = bridge_pb2_grpc.PriceServiceStub(channel)
            start = time.perf_counter()
            response = stub.GetMidPrice(
                request,
                timeout=self.cfg.timeout_s,
                metadata=self._metadata(),
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "coin": response.coin,
                "price": response.price,
                "ts_ms": response.ts_ms,
                "source": response.source,
                "channel": response.channel,
                "latency_ms": round(elapsed_ms, 3),
            }

    def get_block_number(self) -> dict[str, Any]:
        request = bridge_pb2.BlockNumberRequest()
        with self._channel() as channel:
            stub = bridge_pb2_grpc.PriceServiceStub(channel)
            start = time.perf_counter()
            response = stub.GetBlockNumber(
                request,
                timeout=self.cfg.timeout_s,
                metadata=self._metadata(),
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "hex": response.hex,
                "number": response.number,
                "ts_ms": response.ts_ms,
                "latency_ms": round(elapsed_ms, 3),
            }

    def stream_mids(
        self,
        *,
        coin: str = "BTC",
        subscription: str = "allMids",
        heartbeat_s: int = 10,
        max_messages: int = 10,
    ) -> list[dict[str, Any]]:
        request = bridge_pb2.StreamMidsRequest(
            coin=coin,
            subscription=subscription,
            heartbeat_s=heartbeat_s,
        )
        output: list[dict[str, Any]] = []
        with self._channel() as channel:
            stub = bridge_pb2_grpc.PriceServiceStub(channel)
            stream = stub.StreamMids(
                request,
                timeout=max(self.cfg.timeout_s, float(heartbeat_s) * max_messages + 2),
                metadata=self._metadata(),
            )
            for idx, item in enumerate(stream):
                output.append(
                    {
                        "coin": item.coin,
                        "price": item.price,
                        "ts_ms": item.ts_ms,
                        "source": item.source,
                        "channel": item.channel,
                    }
                )
                if idx + 1 >= max_messages:
                    break
        return output

    def grpcurl_invoke(
        self,
        *,
        method: str,
        request_json: str = "{}",
        proto: str | None = None,
        import_path: str | None = None,
        insecure_tls: bool = False,
    ) -> dict[str, Any]:
        cmd: list[str] = ["grpcurl", "-max-time", str(int(self.cfg.timeout_s))]
        if self.cfg.use_tls:
            if insecure_tls:
                cmd.append("-insecure")
            elif self.cfg.ca_cert_path:
                cmd.extend(["-cacert", self.cfg.ca_cert_path])
        else:
            cmd.append("-plaintext")
        if self.cfg.server_name:
            cmd.extend(["-authority", self.cfg.server_name])
        if self.cfg.api_key:
            cmd.extend(["-H", f"x-api-key: {self.cfg.api_key}"])
        if proto:
            cmd.extend(["-proto", proto])
        if import_path:
            cmd.extend(["-import-path", import_path])
        cmd.extend(["-d", request_json, self.cfg.target, method])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return {
                "command": cmd,
                "returncode": 127,
                "stdout": "",
                "stderr": "grpcurl not found. Install it first (for example: brew install grpcurl).",
            }
        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
