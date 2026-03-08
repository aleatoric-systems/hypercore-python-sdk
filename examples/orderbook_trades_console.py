#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import websockets

# Allow running directly via: python3 examples/orderbook_trades_console.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_credentials() -> None:
    candidates = [
        PROJECT_ROOT / "api" / ".env",
        PROJECT_ROOT / ".env",
        Path.cwd() / "api" / ".env",
        Path.cwd() / ".env",
    ]

    for path in candidates:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value

    if "HYPER_API_KEY" not in os.environ and "API_KEY" in os.environ:
        os.environ["HYPER_API_KEY"] = os.environ["API_KEY"]


_load_env_credentials()

from hypercore_sdk import SDKConfig


@dataclass(slots=True)
class TradeEvent:
    side: str
    price: float
    size: float
    ts_ms: int | None
    ingest_latency_ms: float | None


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return fallback


def _safe_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _parse_book_levels(payload: dict[str, object]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ([], [])

    levels = data.get("levels")
    if not (isinstance(levels, list) and len(levels) >= 2):
        return ([], [])

    def _parse_side(raw_levels: object) -> list[tuple[float, float]]:
        if not isinstance(raw_levels, list):
            return []
        out: list[tuple[float, float]] = []
        for item in raw_levels:
            if not isinstance(item, dict):
                continue
            px = _safe_float(item.get("px"))
            sz = _safe_float(item.get("sz"))
            out.append((px, sz))
        return out

    bids = _parse_side(levels[0])
    asks = _parse_side(levels[1])
    return (bids, asks)


def _parse_trades(payload: dict[str, object], coin: str) -> list[TradeEvent]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []

    out: list[TradeEvent] = []
    now_ms = int(time.time() * 1000)
    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("coin", "")).upper() != coin.upper():
            continue

        price = _safe_float(item.get("px"))
        size = _safe_float(item.get("sz"))
        side = str(item.get("side", "?")).upper()
        ts_ms = _safe_int(item.get("time"))
        latency = float(max(0, now_ms - ts_ms)) if ts_ms is not None else None

        out.append(
            TradeEvent(
                side=side,
                price=price,
                size=size,
                ts_ms=ts_ms,
                ingest_latency_ms=latency,
            )
        )
    return out


def _fmt_num(value: float, *, width: int, precision: int) -> str:
    return f"{value:>{width},.{precision}f}"


def _fmt_latency(latency_ms: float | None) -> str:
    if latency_ms is None:
        return "-"
    return f"{latency_ms:.1f}"


def _render_screen(
    *,
    coin: str,
    depth: int,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    trades: deque[TradeEvent],
    ws_url: str,
    started_at: float,
) -> str:
    lines: list[str] = []
    elapsed_s = time.time() - started_at

    lines.append(f"Hypercore live ladder + trades | coin={coin} | uptime={elapsed_s:.1f}s")
    lines.append(f"ws={ws_url}")
    lines.append("")
    lines.append("Orderbook ladder (top levels)")
    lines.append("ASK_SIZE          ASK_PX || BID_PX          BID_SIZE")
    lines.append("------------------------++------------------------")

    for idx in range(depth):
        ask_str = " " * 24
        bid_str = " " * 24

        if idx < len(asks):
            ask_px, ask_sz = asks[idx]
            ask_str = f"{_fmt_num(ask_sz, width=10, precision=4)} {_fmt_num(ask_px, width=12, precision=2)}"

        if idx < len(bids):
            bid_px, bid_sz = bids[idx]
            bid_str = f"{_fmt_num(bid_px, width=12, precision=2)} {_fmt_num(bid_sz, width=10, precision=4)}"

        lines.append(f"{ask_str} || {bid_str}")

    lines.append("")
    lines.append("Recent trades (newest first)")
    lines.append("TIME_MS        SIDE      PRICE        SIZE      LAG_MS")
    lines.append("------------------------------------------------------")

    for trade in list(trades)[::-1]:
        ts = str(trade.ts_ms) if trade.ts_ms is not None else "-"
        lines.append(
            f"{ts:>13} {trade.side:>6} {_fmt_num(trade.price, width=11, precision=2)} "
            f"{_fmt_num(trade.size, width=10, precision=4)} {_fmt_latency(trade.ingest_latency_ms):>10}"
        )

    lines.append("")
    lines.append("Ctrl+C to exit.")

    return "\n".join(lines)


async def run_console(
    *,
    ws_url: str,
    coin: str,
    depth: int,
    trade_limit: int,
    refresh_ms: int,
    api_key: str | None,
    timeout_s: float,
) -> None:
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    bids: list[tuple[float, float]] = []
    asks: list[tuple[float, float]] = []
    recent_trades: deque[TradeEvent] = deque(maxlen=trade_limit)

    started_at = time.time()
    last_render = 0.0

    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}}))
        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}))

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            except asyncio.TimeoutError:
                # Keep rendering heartbeat even when no updates arrive.
                pass
            else:
                msg = json.loads(raw)
                channel = msg.get("channel")
                if channel == "l2Book":
                    bids, asks = _parse_book_levels(msg)
                elif channel == "trades":
                    for trade in _parse_trades(msg, coin):
                        recent_trades.append(trade)

            now = time.perf_counter()
            if (now - last_render) * 1000.0 >= float(refresh_ms):
                frame = _render_screen(
                    coin=coin,
                    depth=depth,
                    bids=bids,
                    asks=asks,
                    trades=recent_trades,
                    ws_url=ws_url,
                    started_at=started_at,
                )
                print("\033[2J\033[H" + frame, end="", flush=True)
                last_render = now


def build_parser() -> argparse.ArgumentParser:
    cfg = SDKConfig()
    parser = argparse.ArgumentParser(description="Live orderbook ladder + trade tape console app.")
    parser.add_argument("--coin", default="BTC", help="Asset symbol, for example BTC or ETH.")
    parser.add_argument("--ws-url", default=cfg.ws_url)
    parser.add_argument("--api-key", default=cfg.api_key)
    parser.add_argument("--depth", type=int, default=12, help="Number of book levels to render per side.")
    parser.add_argument("--trade-limit", type=int, default=20, help="Number of recent trades kept in memory.")
    parser.add_argument("--refresh-ms", type=int, default=250, help="Screen refresh interval.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Socket read timeout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        asyncio.run(
            run_console(
                ws_url=args.ws_url,
                coin=args.coin,
                depth=max(1, int(args.depth)),
                trade_limit=max(1, int(args.trade_limit)),
                refresh_ms=max(50, int(args.refresh_ms)),
                api_key=args.api_key,
                timeout_s=max(1.0, float(args.timeout)),
            )
        )
        return 0
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
