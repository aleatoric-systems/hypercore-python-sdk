from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any, Literal

_IMPORT_ERR: Exception | None = None

try:
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants as hl_constants
    from hyperliquid.utils.types import Cloid
except Exception as exc:  # pragma: no cover - depends on runtime environment
    Account = None  # type: ignore[assignment]
    Exchange = None  # type: ignore[assignment]
    Info = None  # type: ignore[assignment]
    Cloid = None  # type: ignore[assignment]
    hl_constants = None  # type: ignore[assignment]
    _IMPORT_ERR = exc


TradeInterface = Literal["exchange", "info", "all"]


def _require_hyperliquid_sdk() -> None:
    if _IMPORT_ERR is None:
        return
    raise RuntimeError(
        "Missing Hyperliquid trading dependencies. Install with: "
        "python3 -m pip install hyperliquid-python-sdk"
    ) from _IMPORT_ERR


def _extract_actions(cls: type[Any]) -> dict[str, str]:
    actions: dict[str, str] = {}
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        try:
            sig = str(inspect.signature(fn))
        except Exception:
            sig = "(...)"
        actions[name] = sig
    return actions


def list_trading_actions(interface: TradeInterface = "all") -> dict[str, dict[str, str]]:
    _require_hyperliquid_sdk()
    result: dict[str, dict[str, str]] = {}
    if interface in {"exchange", "all"}:
        result["exchange"] = _extract_actions(Exchange)
    if interface in {"info", "all"}:
        result["info"] = _extract_actions(Info)
    return result


def _coerce_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"cloid", "oid"} and isinstance(item, str) and item.startswith("0x"):
                out[key] = Cloid.from_str(item)
            else:
                out[key] = _coerce_value(item)
        return out
    if isinstance(value, list):
        return [_coerce_value(item) for item in value]
    return value


@dataclass(slots=True)
class TradingConfig:
    base_url: str = os.getenv("HYPER_TRADING_BASE_URL", "https://api.hyperliquid.xyz")
    private_key: str | None = os.getenv("HYPER_PRIVATE_KEY")
    vault_address: str | None = os.getenv("HYPER_VAULT_ADDRESS")
    account_address: str | None = os.getenv("HYPER_ACCOUNT_ADDRESS")
    timeout_s: float = float(os.getenv("HYPER_TRADING_TIMEOUT_S", "10"))
    skip_ws: bool = True


class HyperCoreTradingClient:
    def __init__(self, cfg: TradingConfig):
        _require_hyperliquid_sdk()
        self.cfg = cfg

        self.info = Info(base_url=cfg.base_url, skip_ws=cfg.skip_ws, timeout=cfg.timeout_s)
        self.exchange = None
        self.wallet_address: str | None = None

        if cfg.private_key:
            wallet = Account.from_key(cfg.private_key)
            self.wallet_address = wallet.address
            self.exchange = Exchange(
                wallet,
                base_url=cfg.base_url,
                vault_address=cfg.vault_address,
                account_address=cfg.account_address,
                timeout=cfg.timeout_s,
            )

    def _get_interface(self, interface: Literal["exchange", "info"]) -> Any:
        if interface == "info":
            return self.info
        if self.exchange is None:
            raise RuntimeError(
                "Exchange interface requires signing key. Set HYPER_PRIVATE_KEY "
                "or pass --private-key."
            )
        return self.exchange

    def invoke(self, interface: Literal["exchange", "info"], method: str, **kwargs: Any) -> Any:
        target = self._get_interface(interface)
        if not hasattr(target, method):
            raise ValueError(f"Unknown {interface} method: {method}")
        fn = getattr(target, method)
        if not callable(fn):
            raise ValueError(f"{interface}.{method} is not callable")
        coerced_kwargs = _coerce_value(kwargs)
        return fn(**coerced_kwargs)

    def order(
        self,
        *,
        coin: str,
        side: Literal["buy", "sell"],
        sz: float,
        limit_px: float,
        order_type: dict[str, Any],
        reduce_only: bool = False,
        cloid: str | None = None,
        builder: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "name": coin,
            "is_buy": side.lower() == "buy",
            "sz": sz,
            "limit_px": limit_px,
            "order_type": order_type,
            "reduce_only": reduce_only,
            "builder": builder,
        }
        if cloid:
            payload["cloid"] = cloid
        return self.invoke("exchange", "order", **payload)

    def cancel(self, *, coin: str, oid: int) -> Any:
        return self.invoke("exchange", "cancel", name=coin, oid=oid)

    def cancel_by_cloid(self, *, coin: str, cloid: str) -> Any:
        return self.invoke("exchange", "cancel_by_cloid", name=coin, cloid=cloid)

    def metadata(self) -> dict[str, Any]:
        return {
            "base_url": self.cfg.base_url,
            "wallet_address": self.wallet_address,
            "has_signing": self.exchange is not None,
            "network": (
                "mainnet"
                if hl_constants and self.cfg.base_url == hl_constants.MAINNET_API_URL
                else "custom"
            ),
        }
