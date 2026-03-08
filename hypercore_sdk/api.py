from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from .config import SDKConfig


class HyperCoreAPI:
    """High-performance HTTP client for HyperCore RPC and info endpoints.

    Reuses a single HTTP client instance for connection pooling and lower tail latency.
    """

    def __init__(self, config: SDKConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.config.timeout_s,
            verify=self.config.verify_tls,
            headers={"content-type": "application/json"},
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HyperCoreAPI":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        self.close()
        return False

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        response = self._client.post(url, headers=headers, content=json.dumps(payload))
        response.raise_for_status()
        return response.json()

    def rpc_call(self, method: str, params: list[Any] | None = None, request_id: int = 1) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": request_id,
        }
        body = self._post_json(self.config.rpc_url, payload, headers=self.config.auth_headers())
        if isinstance(body, dict) and "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected RPC response payload: {body!r}")
        return body.get("result")

    def info_call(self, info_type: str, **kwargs: Any) -> Any:
        payload: dict[str, Any] = {"type": info_type}
        payload.update(kwargs)
        return self._post_json(self.config.info_url, payload, headers=self.config.auth_headers())

    def block_number(self) -> int:
        raw = self.rpc_call("eth_blockNumber")
        if isinstance(raw, str) and raw.startswith("0x"):
            return int(raw, 16)
        raise RuntimeError(f"Unexpected block number payload: {raw!r}")

    def all_mids(self, dex: str = "") -> dict[str, str]:
        body = self.info_call("allMids", dex=dex)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected allMids payload: {body!r}")
        mids: dict[str, str] = {}
        for key, value in body.items():
            mids[str(key)] = str(value)
        return mids

    def coin_mid(self, coin: str, dex: str = "") -> float:
        mids = self.all_mids(dex=dex)
        if coin not in mids:
            raise RuntimeError(f"Coin {coin} not present in allMids response.")
        return float(mids[coin])

    def meta(self, dex: str = "") -> dict[str, Any]:
        body = self.info_call("meta", dex=dex)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected meta payload: {body!r}")
        return body

    def spot_meta(self) -> dict[str, Any]:
        body = self.info_call("spotMeta")
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected spotMeta payload: {body!r}")
        return body

    def meta_and_asset_ctxs(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        body = self.info_call("metaAndAssetCtxs")
        if not isinstance(body, list) or len(body) != 2 or not isinstance(body[0], dict) or not isinstance(body[1], list):
            raise RuntimeError(f"Unexpected metaAndAssetCtxs payload: {body!r}")

        ctxs: list[dict[str, Any]] = []
        for item in body[1]:
            if isinstance(item, dict):
                ctxs.append(item)
            else:
                raise RuntimeError(f"Invalid asset context entry: {item!r}")
        return body[0], ctxs

    def spot_meta_and_asset_ctxs(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        body = self.info_call("spotMetaAndAssetCtxs")
        if not isinstance(body, list) or len(body) != 2 or not isinstance(body[0], dict) or not isinstance(body[1], list):
            raise RuntimeError(f"Unexpected spotMetaAndAssetCtxs payload: {body!r}")

        ctxs: list[dict[str, Any]] = []
        for item in body[1]:
            if isinstance(item, dict):
                ctxs.append(item)
            else:
                raise RuntimeError(f"Invalid spot asset context entry: {item!r}")
        return body[0], ctxs

    def l2_snapshot(self, coin: str) -> dict[str, Any]:
        body = self.info_call("l2Book", coin=coin)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected l2Book payload: {body!r}")
        return body

    def candles_snapshot(self, coin: str, interval: str, start_time_ms: int, end_time_ms: int) -> list[dict[str, Any]]:
        req = {
            "coin": coin,
            "interval": interval,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
        }
        body = self.info_call("candleSnapshot", req=req)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected candleSnapshot payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def funding_history(self, coin: str, start_time_ms: int, end_time_ms: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "coin": coin,
            "startTime": start_time_ms,
        }
        if end_time_ms is not None:
            payload["endTime"] = end_time_ms
        body = self.info_call("fundingHistory", **payload)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected fundingHistory payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_state(self, address: str, dex: str = "") -> dict[str, Any]:
        body = self.info_call("clearinghouseState", user=address, dex=dex)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected clearinghouseState payload: {body!r}")
        return body

    def spot_user_state(self, address: str) -> dict[str, Any]:
        body = self.info_call("spotClearinghouseState", user=address)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected spotClearinghouseState payload: {body!r}")
        return body

    def open_orders(self, address: str, dex: str = "") -> list[dict[str, Any]]:
        body = self.info_call("openOrders", user=address, dex=dex)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected openOrders payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def frontend_open_orders(self, address: str, dex: str = "") -> list[dict[str, Any]]:
        body = self.info_call("frontendOpenOrders", user=address, dex=dex)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected frontendOpenOrders payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_fills(self, address: str) -> list[dict[str, Any]]:
        body = self.info_call("userFills", user=address)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected userFills payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_fills_by_time(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int | None = None,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "user": address,
            "startTime": start_time_ms,
            "aggregateByTime": aggregate_by_time,
        }
        if end_time_ms is not None:
            payload["endTime"] = end_time_ms

        body = self.info_call("userFillsByTime", **payload)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected userFillsByTime payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def portfolio(self, address: str) -> dict[str, Any]:
        body = self.info_call("portfolio", user=address)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected portfolio payload: {body!r}")
        return body

    def user_non_funding_ledger_updates(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        body = self.info_call(
            "userNonFundingLedgerUpdates",
            user=address,
            startTime=start_time_ms,
            endTime=end_time_ms,
        )
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected userNonFundingLedgerUpdates payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def historical_orders(self, address: str) -> list[dict[str, Any]]:
        body = self.info_call("historicalOrders", user=address)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected historicalOrders payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_twap_slice_fills(self, address: str) -> list[dict[str, Any]]:
        body = self.info_call("userTwapSliceFills", user=address)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected userTwapSliceFills payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_vault_equities(self, address: str) -> list[dict[str, Any]]:
        body = self.info_call("userVaultEquities", user=address)
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected userVaultEquities payload: {body!r}")
        return [item for item in body if isinstance(item, dict)]

    def user_role(self, address: str) -> dict[str, Any]:
        body = self.info_call("userRole", user=address)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected userRole payload: {body!r}")
        return body

    def user_rate_limit(self, address: str) -> dict[str, Any]:
        body = self.info_call("userRateLimit", user=address)
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected userRateLimit payload: {body!r}")
        return body

    @staticmethod
    def summarize_fills(fills: list[dict[str, Any]]) -> dict[str, Any]:
        total_notional = 0.0
        total_size = 0.0
        by_coin: dict[str, dict[str, float | int]] = {}
        latest_fill_ms = 0

        for fill in fills:
            coin = str(fill.get("coin", "UNKNOWN"))
            px = float(fill.get("px", 0.0))
            sz = float(fill.get("sz", 0.0))
            ts = int(fill.get("time", 0))
            notional = px * sz

            total_notional += notional
            total_size += sz
            latest_fill_ms = max(latest_fill_ms, ts)

            if coin not in by_coin:
                by_coin[coin] = {
                    "fills": 0,
                    "size": 0.0,
                    "notional": 0.0,
                }
            by_coin[coin]["fills"] = int(by_coin[coin]["fills"]) + 1
            by_coin[coin]["size"] = float(by_coin[coin]["size"]) + sz
            by_coin[coin]["notional"] = float(by_coin[coin]["notional"]) + notional

        return {
            "fills": len(fills),
            "total_notional": round(total_notional, 8),
            "total_size": round(total_size, 8),
            "latest_fill_ms": latest_fill_ms,
            "by_coin": by_coin,
        }

    @staticmethod
    def summarize_funding_history(records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            return {
                "count": 0,
                "avg_funding_rate": 0.0,
                "min_funding_rate": 0.0,
                "max_funding_rate": 0.0,
                "latest_time_ms": 0,
            }

        rates: list[float] = []
        latest_time_ms = 0
        for row in records:
            rate = float(row.get("fundingRate", 0.0))
            rates.append(rate)
            latest_time_ms = max(latest_time_ms, int(row.get("time", 0)))

        return {
            "count": len(records),
            "avg_funding_rate": sum(rates) / len(rates),
            "min_funding_rate": min(rates),
            "max_funding_rate": max(rates),
            "latest_time_ms": latest_time_ms,
        }

    @staticmethod
    def summarize_non_funding_ledger_updates(updates: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "count": len(updates),
            "by_type": {},
            "latest_time_ms": 0,
        }
        by_type: dict[str, int] = {}
        latest_time_ms = 0
        for row in updates:
            event_type = str(row.get("type", "unknown"))
            by_type[event_type] = by_type.get(event_type, 0) + 1
            latest_time_ms = max(latest_time_ms, int(row.get("time", 0)))
        summary["by_type"] = by_type
        summary["latest_time_ms"] = latest_time_ms
        return summary

    def top_of_book(self, coin: str) -> dict[str, float]:
        snapshot = self.l2_snapshot(coin)
        levels = snapshot.get("levels")
        if (
            not isinstance(levels, list)
            or len(levels) < 2
            or not isinstance(levels[0], list)
            or not isinstance(levels[1], list)
            or not levels[0]
            or not levels[1]
            or not isinstance(levels[0][0], dict)
            or not isinstance(levels[1][0], dict)
        ):
            raise RuntimeError(f"Unexpected l2Book level structure: {snapshot!r}")

        bid = float(levels[0][0]["px"])
        ask = float(levels[1][0]["px"])
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_bps = 0.0
        if mid > 0:
            spread_bps = (spread / mid) * 10000.0

        return {
            "best_bid": bid,
            "best_ask": ask,
            "mid": mid,
            "spread": spread,
            "spread_bps": spread_bps,
        }

    def orderbook_imbalance(self, coin: str, depth: int = 5) -> dict[str, float]:
        snapshot = self.l2_snapshot(coin)
        levels = snapshot.get("levels")
        if (
            not isinstance(levels, list)
            or len(levels) < 2
            or not isinstance(levels[0], list)
            or not isinstance(levels[1], list)
        ):
            raise RuntimeError(f"Unexpected l2Book level structure: {snapshot!r}")

        bids = levels[0][:depth]
        asks = levels[1][:depth]

        bid_notional = 0.0
        ask_notional = 0.0
        for row in bids:
            if not isinstance(row, dict):
                continue
            bid_notional += float(row.get("px", 0.0)) * float(row.get("sz", 0.0))
        for row in asks:
            if not isinstance(row, dict):
                continue
            ask_notional += float(row.get("px", 0.0)) * float(row.get("sz", 0.0))

        total = bid_notional + ask_notional
        imbalance = 0.0
        if total > 0:
            imbalance = (bid_notional - ask_notional) / total

        return {
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "imbalance": imbalance,
            "depth": float(depth),
        }

    def asset_ctx(self, coin: str) -> dict[str, Any]:
        meta, ctxs = self.meta_and_asset_ctxs()
        universe = meta.get("universe")
        if not isinstance(universe, list):
            raise RuntimeError(f"Unexpected meta universe payload: {meta!r}")

        for idx, item in enumerate(universe):
            if not isinstance(item, dict):
                continue
            if str(item.get("name")) == coin and idx < len(ctxs):
                return ctxs[idx]
        raise RuntimeError(f"Coin {coin} not found in metaAndAssetCtxs universe.")

    def market_snapshot(self, coin: str) -> dict[str, Any]:
        return {
            "coin": coin,
            "mid_px": self.coin_mid(coin),
            "top_of_book": self.top_of_book(coin),
            "orderbook_imbalance": self.orderbook_imbalance(coin, depth=5),
            "asset_ctx": self.asset_ctx(coin),
        }

    def user_flow_snapshot(self, address: str, dex: str = "") -> dict[str, Any]:
        fills = self.user_fills(address)
        return {
            "address": address,
            "user_state": self.user_state(address, dex=dex),
            "open_orders": self.open_orders(address, dex=dex),
            "fill_summary": self.summarize_fills(fills),
        }

    def funding_snapshot(self, coin: str, start_time_ms: int, end_time_ms: int | None = None) -> dict[str, Any]:
        rows = self.funding_history(coin, start_time_ms, end_time_ms=end_time_ms)
        return {
            "coin": coin,
            "window": {
                "start_time_ms": start_time_ms,
                "end_time_ms": end_time_ms,
            },
            "summary": self.summarize_funding_history(rows),
            "rows": rows,
        }

    def user_activity_snapshot(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int | None = None,
        dex: str = "",
    ) -> dict[str, Any]:
        fills = self.user_fills_by_time(
            address,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            aggregate_by_time=True,
        )
        ledger_updates = self.user_non_funding_ledger_updates(
            address,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        return {
            "address": address,
            "window": {
                "start_time_ms": start_time_ms,
                "end_time_ms": end_time_ms,
            },
            "user_state": self.user_state(address, dex=dex),
            "fills": fills,
            "fills_summary": self.summarize_fills(fills),
            "ledger_updates": ledger_updates,
            "ledger_summary": self.summarize_non_funding_ledger_updates(ledger_updates),
        }
