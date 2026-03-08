from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import websockets


def _extract_price(channel: str, payload: dict[str, Any], coin: str) -> float | None:
    data = payload.get("data")
    if channel == "allMids" and isinstance(data, dict):
        mids = data.get("mids")
        if isinstance(mids, dict) and coin in mids:
            return float(mids[coin])

    if channel == "trades" and isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get("coin") == coin and "px" in first:
            return float(first["px"])

    if channel == "l2Book" and isinstance(data, dict):
        if data.get("coin") != coin:
            return None
        levels = data.get("levels")
        if (
            isinstance(levels, list)
            and len(levels) >= 2
            and isinstance(levels[0], list)
            and isinstance(levels[1], list)
            and levels[0]
            and levels[1]
        ):
            best_bid = float(levels[0][0]["px"])
            best_ask = float(levels[1][0]["px"])
            return (best_bid + best_ask) / 2.0
    return None


async def get_price_from_ws(
    *,
    ws_url: str,
    coin: str = "BTC",
    subscription_type: str = "allMids",
    timeout_s: float = 10.0,
    api_key: str | None = None,
    max_message_bytes: int | None = None,
) -> dict[str, Any]:
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    subscription: dict[str, Any] = {"type": subscription_type}
    if subscription_type in {"trades", "l2Book"}:
        subscription["coin"] = coin

    start = time.perf_counter()
    async with websockets.connect(
        ws_url,
        additional_headers=headers,
        max_size=max_message_bytes,
    ) as ws:
        await ws.send(json.dumps({"method": "subscribe", "subscription": subscription}))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            msg = json.loads(raw)
            channel = msg.get("channel")
            if channel in {"subscriptionResponse", "pong"}:
                continue
            price = _extract_price(channel, msg, coin)
            if price is None:
                continue
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "coin": coin,
                "price": price,
                "channel": channel,
                "latency_ms": round(elapsed_ms, 3),
                "message": msg,
            }
