from __future__ import annotations

import json
from typing import Any

import httpx

from .config import SDKConfig


class HyperCoreAPI:
    def __init__(self, config: SDKConfig):
        self.config = config

    def rpc_call(self, method: str, params: list[Any] | None = None, request_id: int = 1) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": request_id,
        }
        with httpx.Client(timeout=self.config.timeout_s, verify=self.config.verify_tls) as client:
            response = client.post(
                self.config.rpc_url,
                headers=self.config.auth_headers(),
                content=json.dumps(payload),
            )
            response.raise_for_status()
            body = response.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body.get("result")

    def block_number(self) -> int:
        raw = self.rpc_call("eth_blockNumber")
        if isinstance(raw, str) and raw.startswith("0x"):
            return int(raw, 16)
        raise RuntimeError(f"Unexpected block number payload: {raw!r}")

    def all_mids(self) -> dict[str, str]:
        payload = {"type": "allMids"}
        with httpx.Client(timeout=self.config.timeout_s, verify=self.config.verify_tls) as client:
            response = client.post(
                self.config.info_url,
                headers={"content-type": "application/json"},
                content=json.dumps(payload),
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected allMids payload: {body!r}")
        mids: dict[str, str] = {}
        for key, value in body.items():
            mids[str(key)] = str(value)
        return mids

    def coin_mid(self, coin: str) -> float:
        mids = self.all_mids()
        if coin not in mids:
            raise RuntimeError(f"Coin {coin} not present in allMids response.")
        return float(mids[coin])
