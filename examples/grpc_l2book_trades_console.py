#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import grpc

# Allow running directly via: python3 examples/grpc_l2book_trades_console.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hypercore_sdk import SDKConfig
from hypercore_sdk.example_auth import grpc_key_candidates, load_env_credentials, pick_key
from hypercore_sdk.grpc_client import GrpcClient, GrpcConnectionConfig
from hypercore_sdk.proto import hypercore_bridge_pb2 as bridge_pb2
from hypercore_sdk.proto import hypercore_bridge_pb2_grpc as bridge_pb2_grpc


SUBSCRIPTIONS = ("l2Book", "trades")


@dataclass(slots=True)
class FeedUpdate:
    subscription: str
    coin: str
    price: float
    ts_ms: int | None
    source: str
    channel: str
    received_at_ms: int
    ingest_latency_ms: float | None


@dataclass(slots=True)
class FeedError:
    subscription: str
    code: str
    details: str
    at_ms: int


@dataclass(slots=True)
class FeedState:
    subscription: str
    latest: FeedUpdate | None = None
    updates: int = 0
    error: str | None = None


@dataclass(slots=True)
class AuthPreflight:
    key_source: str
    key_present: bool
    health_status: str | None = None
    health_latency_ms: float | None = None
    health_error_code: str | None = None
    health_error: str | None = None
    price_service_status: str | None = None
    price_service_error_code: str | None = None
    price_service_error: str | None = None
    diagnosis: str | None = None


def _safe_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _event_payload(item: Any, *, subscription: str) -> FeedUpdate:
    now_ms = int(time.time() * 1000)
    ts_ms = _safe_positive_int(getattr(item, "ts_ms", None))
    ingest_latency_ms = float(max(0, now_ms - ts_ms)) if ts_ms is not None else None
    return FeedUpdate(
        subscription=subscription,
        coin=str(getattr(item, "coin", "")),
        price=float(getattr(item, "price", 0.0)),
        ts_ms=ts_ms,
        source=str(getattr(item, "source", "")),
        channel=str(getattr(item, "channel", subscription)),
        received_at_ms=now_ms,
        ingest_latency_ms=ingest_latency_ms,
    )


def _fmt_num(value: float, *, width: int, precision: int) -> str:
    return f"{value:>{width},.{precision}f}"


def _fmt_latency(latency_ms: float | None) -> str:
    if latency_ms is None:
        return "-"
    return f"{latency_ms:.1f}"


def _fmt_age_ms(now_ms: int, received_at_ms: int | None) -> str:
    if received_at_ms is None:
        return "-"
    return f"{max(0, now_ms - received_at_ms):.1f}"


def _price_delta_bps(l2book_price: float | None, trades_price: float | None) -> float | None:
    if l2book_price is None or trades_price is None or trades_price == 0:
        return None
    return round(((l2book_price - trades_price) / trades_price) * 10_000.0, 6)


def _resolve_api_key(cli_value: str | None, cfg: SDKConfig) -> tuple[str | None, str]:
    if cli_value:
        return pick_key(cli_value, []).value, "--api-key"
    resolution = pick_key(cli_value, [*grpc_key_candidates(), ("SDKConfig.api_key", cfg.api_key)])
    return resolution.value, resolution.source or "none"


def _is_auth_denial(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return (
        "permission_denied" in lowered
        or "status: 403" in lowered
        or "status code 403" in lowered
        or "http 403" in lowered
    )


def _run_health_preflight(cfg: GrpcConnectionConfig, key_source: str) -> AuthPreflight:
    preflight = AuthPreflight(key_source=key_source, key_present=bool(cfg.api_key))
    try:
        result = GrpcClient(cfg).health_check()
        preflight.health_status = str(result.get("status", ""))
        latency_ms = result.get("latency_ms")
        if latency_ms is not None:
            preflight.health_latency_ms = float(latency_ms)
    except grpc.RpcError as exc:
        preflight.health_error_code = str(exc.code())
        preflight.health_error = exc.details() or str(exc)
    except Exception as exc:
        preflight.health_error = str(exc)
    return preflight


def _run_price_service_preflight(
    cfg: GrpcConnectionConfig,
    *,
    coin: str,
    preflight: AuthPreflight,
) -> AuthPreflight:
    try:
        GrpcClient(cfg).get_mid_price(coin=coin)
        preflight.price_service_status = "ok"
    except grpc.RpcError as exc:
        preflight.price_service_error_code = str(exc.code())
        preflight.price_service_error = exc.details() or str(exc)
    except Exception as exc:
        preflight.price_service_error = str(exc)
    return preflight


def _detect_preflight_auth_diagnosis(preflight: AuthPreflight) -> str | None:
    price_auth_denied = _is_auth_denial(preflight.price_service_error_code) or _is_auth_denial(preflight.price_service_error)
    if not price_auth_denied:
        return None

    health_auth_denied = _is_auth_denial(preflight.health_error_code) or _is_auth_denial(preflight.health_error)
    if preflight.health_status == "SERVING":
        return (
            "health works, PriceService auth denied by endpoint; "
            "streams will fail; "
            f"selected key source: {preflight.key_source}"
        )
    if health_auth_denied:
        return (
            "health and PriceService auth denied by endpoint; "
            f"selected key source: {preflight.key_source}"
        )
    return None


def _detect_auth_diagnosis(states: dict[str, FeedState], preflight: AuthPreflight, total_events: int) -> str | None:
    if total_events > 0:
        return None

    errors = [states[subscription].error or "" for subscription in SUBSCRIPTIONS]
    if not all(errors):
        return None
    if not all(_is_auth_denial(error) for error in errors):
        return None

    health_auth_denied = _is_auth_denial(preflight.health_error_code) or _is_auth_denial(preflight.health_error)
    if preflight.health_status == "SERVING":
        return (
            "health works, stream auth denied by endpoint; "
            f"selected key source: {preflight.key_source}"
        )
    if health_auth_denied:
        return (
            "health and stream auth denied by endpoint; "
            f"selected key source: {preflight.key_source}"
        )
    return None


def _render_screen(
    *,
    coin: str,
    target: str,
    heartbeat_s: int,
    preflight: AuthPreflight,
    started_at: float,
    states: dict[str, FeedState],
    history: deque[FeedUpdate],
    total_events: int,
) -> str:
    now = time.time()
    now_ms = int(now * 1000)
    elapsed_s = now - started_at
    lines: list[str] = []

    lines.append(f"Hypercore gRPC live feeds | coin={coin} | uptime={elapsed_s:.1f}s")
    lines.append(f"target={target} | heartbeat={heartbeat_s}s | events={total_events}")
    lines.append(
        f"key_source={preflight.key_source} | key_present={'yes' if preflight.key_present else 'no'}"
    )
    if preflight.health_status:
        lines.append(
            f"health={preflight.health_status} | health_latency_ms={_fmt_latency(preflight.health_latency_ms)}"
        )
    elif preflight.health_error:
        label = "auth_denied" if (
            _is_auth_denial(preflight.health_error_code) or _is_auth_denial(preflight.health_error)
        ) else "error"
        parts = [f"health={label}"]
        if preflight.health_error_code:
            parts.append(preflight.health_error_code)
        parts.append(preflight.health_error)
        lines.append(" | ".join(parts))
    if preflight.price_service_status:
        lines.append(f"price_service={preflight.price_service_status}")
    elif preflight.price_service_error:
        label = "auth_denied" if (
            _is_auth_denial(preflight.price_service_error_code) or _is_auth_denial(preflight.price_service_error)
        ) else "error"
        parts = [f"price_service={label}"]
        if preflight.price_service_error_code:
            parts.append(preflight.price_service_error_code)
        parts.append(preflight.price_service_error)
        lines.append(" | ".join(parts))
    if preflight.diagnosis:
        lines.append(f"diagnosis={preflight.diagnosis}")
    lines.append("")
    lines.append("Latest channel snapshot")
    lines.append("SUB         STATUS        PRICE          TS_MS      AGE_MS      LAG_MS  UPDATES SOURCE     CHANNEL")
    lines.append("---------------------------------------------------------------------------------------------------")

    l2book_price: float | None = None
    trades_price: float | None = None

    for subscription in SUBSCRIPTIONS:
        state = states[subscription]
        if state.latest is None:
            status = "error" if state.error else "waiting"
            lines.append(
                f"{subscription:<10} {status:<10} {'-':>12} {'-':>13} {'-':>11} {'-':>11} "
                f"{state.updates:>7} {'-':<10} {'-':<10}"
            )
            continue

        latest = state.latest
        status = "error" if state.error else "live"
        if subscription == "l2Book":
            l2book_price = latest.price
        elif subscription == "trades":
            trades_price = latest.price
        lines.append(
            f"{subscription:<10} {status:<10} {_fmt_num(latest.price, width=12, precision=2)} "
            f"{str(latest.ts_ms or '-'):>13} {_fmt_age_ms(now_ms, latest.received_at_ms):>11} "
            f"{_fmt_latency(latest.ingest_latency_ms):>11} {state.updates:>7} "
            f"{latest.source[:10]:<10} {latest.channel[:10]:<10}"
        )

    delta_bps = _price_delta_bps(l2book_price, trades_price)
    lines.append("")
    if delta_bps is None:
        lines.append("l2Book vs trades delta: n/a")
    else:
        lines.append(f"l2Book vs trades delta: {delta_bps:+.2f} bps")

    lines.append("")
    lines.append("Recent updates (newest first)")
    lines.append("RECV_MS         SUB            PRICE          TS_MS      LAG_MS SOURCE     CHANNEL")
    lines.append("--------------------------------------------------------------------------------")

    for event in list(history)[::-1]:
        lines.append(
            f"{event.received_at_ms:>13} {event.subscription:<10} {_fmt_num(event.price, width=12, precision=2)} "
            f"{str(event.ts_ms or '-'):>13} {_fmt_latency(event.ingest_latency_ms):>11} "
            f"{event.source[:10]:<10} {event.channel[:10]:<10}"
        )

    if not history:
        lines.append("No events received yet.")

    active_errors = [f"{state.subscription}: {state.error}" for state in states.values() if state.error]
    if active_errors:
        lines.append("")
        lines.append("Errors")
        lines.append("------")
        lines.extend(active_errors)

    lines.append("")
    lines.append("Ctrl+C to exit.")
    return "\n".join(lines)


class GrpcFeedWorker(threading.Thread):
    def __init__(
        self,
        *,
        cfg: GrpcConnectionConfig,
        coin: str,
        subscription: str,
        heartbeat_s: int,
        timeout_s: float | None,
        out_queue: Queue[FeedUpdate | FeedError],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name=f"grpc-feed-{subscription}", daemon=True)
        self.cfg = cfg
        self.coin = coin
        self.subscription = subscription
        self.heartbeat_s = heartbeat_s
        self.timeout_s = timeout_s
        self.out_queue = out_queue
        self.stop_event = stop_event
        self._channel: grpc.Channel | None = None
        self._call: Any = None

    def stop(self, *, set_stop_event: bool = True) -> None:
        if set_stop_event:
            self.stop_event.set()
        if self._call is not None:
            try:
                self._call.cancel()
            except Exception:
                pass
        if self._channel is not None:
            self._channel.close()

    def run(self) -> None:
        client = GrpcClient(self.cfg)
        request = bridge_pb2.StreamMidsRequest(
            coin=self.coin,
            subscription=self.subscription,
            heartbeat_s=max(1, int(self.heartbeat_s)),
        )

        try:
            channel = client._channel()
            self._channel = channel
            with channel:
                stub = bridge_pb2_grpc.PriceServiceStub(channel)
                self._call = stub.StreamMids(
                    request,
                    timeout=self.timeout_s,
                    metadata=client._metadata(),
                )
                for item in self._call:
                    if self.stop_event.is_set():
                        break
                    self.out_queue.put(_event_payload(item, subscription=self.subscription))
        except grpc.RpcError as exc:
            if not self.stop_event.is_set() and exc.code() != grpc.StatusCode.CANCELLED:
                self.out_queue.put(
                    FeedError(
                        subscription=self.subscription,
                        code=str(exc.code()),
                        details=exc.details() or "",
                        at_ms=int(time.time() * 1000),
                    )
                )
        except Exception as exc:
            if not self.stop_event.is_set():
                self.out_queue.put(
                    FeedError(
                        subscription=self.subscription,
                        code=type(exc).__name__,
                        details=str(exc),
                        at_ms=int(time.time() * 1000),
                    )
                )
        finally:
            self.stop(set_stop_event=False)


def run_console(
    *,
    target: str,
    coin: str,
    heartbeat_s: int,
    timeout_s: float | None,
    history_limit: int,
    refresh_ms: int,
    max_events: int,
    api_key: str | None,
    key_source: str,
    server_name: str | None,
    plaintext: bool,
) -> int:
    grpc_cfg = GrpcConnectionConfig(
        target=target,
        timeout_s=30.0 if timeout_s is None else timeout_s,
        use_tls=not plaintext,
        server_name=server_name,
        api_key=api_key,
    )
    preflight = _run_health_preflight(grpc_cfg, key_source=key_source)
    preflight = _run_price_service_preflight(grpc_cfg, coin=coin, preflight=preflight)
    preflight.diagnosis = _detect_preflight_auth_diagnosis(preflight)

    stop_event = threading.Event()
    out_queue: Queue[FeedUpdate | FeedError] = Queue()
    states = {subscription: FeedState(subscription=subscription) for subscription in SUBSCRIPTIONS}
    history: deque[FeedUpdate] = deque(maxlen=history_limit)
    workers = [
        GrpcFeedWorker(
            cfg=grpc_cfg,
            coin=coin,
            subscription=subscription,
            heartbeat_s=heartbeat_s,
            timeout_s=timeout_s,
            out_queue=out_queue,
            stop_event=stop_event,
        )
        for subscription in SUBSCRIPTIONS
    ]

    started_at = time.time()
    total_events = 0
    last_render = 0.0
    exit_code = 0

    if preflight.diagnosis:
        frame = _render_screen(
            coin=coin,
            target=target,
            heartbeat_s=heartbeat_s,
            preflight=preflight,
            started_at=started_at,
            states=states,
            history=history,
            total_events=total_events,
        )
        print("\033[2J\033[H" + frame, end="", flush=True)
        return 3

    for worker in workers:
        worker.start()

    try:
        should_stop = False
        while not should_stop:
            pending: list[FeedUpdate | FeedError] = []
            try:
                message = out_queue.get(timeout=max(0.05, float(refresh_ms) / 1000.0))
                pending.append(message)
            except Empty:
                pass

            while True:
                try:
                    pending.append(out_queue.get_nowait())
                except Empty:
                    break

            for message in pending:
                if isinstance(message, FeedUpdate):
                    state = states[message.subscription]
                    state.latest = message
                    state.error = None
                    state.updates += 1
                    history.append(message)
                    total_events += 1
                    if max_events > 0 and total_events >= max_events:
                        should_stop = True
                        break
                else:
                    states[message.subscription].error = f"{message.code} {message.details}".strip()

            now = time.perf_counter()
            if (now - last_render) * 1000.0 >= float(refresh_ms):
                frame = _render_screen(
                    coin=coin,
                    target=target,
                    heartbeat_s=heartbeat_s,
                    preflight=preflight,
                    started_at=started_at,
                    states=states,
                    history=history,
                    total_events=total_events,
                )
                print("\033[2J\033[H" + frame, end="", flush=True)
                last_render = now

            diagnosis = _detect_auth_diagnosis(states, preflight, total_events)
            if diagnosis:
                preflight.diagnosis = diagnosis
                exit_code = 3
                break

            if should_stop:
                break

            if all(not worker.is_alive() for worker in workers):
                if any(state.error for state in states.values()):
                    exit_code = 2
                elif total_events == 0:
                    exit_code = 1
                    for subscription in SUBSCRIPTIONS:
                        if states[subscription].error is None:
                            states[subscription].error = "stream ended before any events were received"
                break
    finally:
        stop_event.set()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=max(1.0, float(heartbeat_s) + 1.0))

    frame = _render_screen(
        coin=coin,
        target=target,
        heartbeat_s=heartbeat_s,
        preflight=preflight,
        started_at=started_at,
        states=states,
        history=history,
        total_events=total_events,
    )
    print("\033[2J\033[H" + frame, end="", flush=True)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    load_env_credentials(PROJECT_ROOT)
    cfg = SDKConfig()

    parser = argparse.ArgumentParser(
        description=(
            "Live console for the normalized gRPC l2Book and trades feeds. "
            "Displays the latest bridge prices for both subscriptions side-by-side."
        )
    )
    parser.add_argument("--coin", default="BTC", help="Asset symbol, for example BTC or ETH.")
    parser.add_argument("--target", default=os.getenv("ALEATORIC_GRPC_TARGET", cfg.grpc_target), help="gRPC host:port")
    parser.add_argument("--server-name", default=os.getenv("ALEATORIC_GRPC_SERVER_NAME", cfg.grpc_server_name), help="TLS SNI/server name override")
    parser.add_argument("--api-key", default=None, help="Explicit gRPC API key override.")
    parser.add_argument("--heartbeat-s", type=int, default=10, help="Bridge heartbeat interval.")
    parser.add_argument(
        "--history-limit",
        type=int,
        default=30,
        help="Number of recent gRPC updates kept in the console tape.",
    )
    parser.add_argument("--refresh-ms", type=int, default=250, help="Screen refresh interval.")
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Stop after N combined updates across both subscriptions (0 means run forever).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.0,
        help="Per-stream RPC deadline in seconds (0 disables the client deadline).",
    )
    parser.add_argument("--plaintext", action="store_true", default=False, help="Disable TLS.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = SDKConfig()
    api_key, key_source = _resolve_api_key(args.api_key, cfg)

    try:
        return run_console(
            target=args.target,
            coin=args.coin,
            heartbeat_s=max(1, int(args.heartbeat_s)),
            timeout_s=None if float(args.timeout) <= 0 else max(1.0, float(args.timeout)),
            history_limit=max(1, int(args.history_limit)),
            refresh_ms=max(50, int(args.refresh_ms)),
            max_events=max(0, int(args.max_events)),
            api_key=api_key,
            key_source=key_source,
            server_name=args.server_name,
            plaintext=args.plaintext,
        )
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
