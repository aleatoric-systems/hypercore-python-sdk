# HyperCore SDK API Interface Reference

This document is the interface contract for the Python SDK in this repository.

Scope:
- Python package: `hypercore_sdk`
- Transport layers: JSON-RPC, Hyperliquid `/info`, WebSocket, gRPC
- Dedicated unified stream transport for pre-decoded events and browser-safe market snapshots
- Status API client and stdio MCP server
- Derived intelligence layer for indexing and analytics

As-of validation (March 7, 2026):
As-of validation (March 13, 2026):
- `pytest`: **127 passed**
- `pytest` with coverage gate: **92.45% total coverage**
- `mypy -p hypercore_sdk`: **no issues found** (16 source files)
- `python -m build`: **passed**
- `python -m twine check dist/*`: **passed**

## 1. Quality, Guarantees, and Limits

Objective quality facts:
- The package is typed (`py.typed`) and mypy-clean under project settings.
- CLI command paths are unit tested with mocked dependencies.
- Core adapters validate response shapes and raise `RuntimeError` on incompatible payloads.
- Coverage is above enforced gate (90%).

Objective limits:
- No benchmark claim is included here comparing throughput/latency to other SDKs.
- `/info` response schemas are upstream-controlled and can evolve.
- gRPC proto-generated modules are runtime-tested; static typing for generated classes is partially suppressed (expected for protobuf codegen).
- This SDK intentionally excludes signing and order placement.

## 2. Configuration Data Structures

## 2.1 `SDKConfig`
File: `hypercore_sdk/config.py`

```python
@dataclass(slots=True)
class SDKConfig:
    rpc_url: str = "https://rpc.aleatoric.systems/"
    ws_url: str = "wss://disk.grpc.aleatoric.systems/"
    info_url: str = "https://api.hyperliquid.xyz/info"
    unified_stream_url: str = "https://unified.grpc.aleatoric.systems"
    status_url: str = "http://127.0.0.1:8090"
    grpc_target: str = "hl.grpc.aleatoric.systems:443"
    api_key: str | None = None
    unified_stream_api_key: str | None = None
    grpc_api_key: str | None = None
    status_token: str | None = None
    timeout_s: float = 10.0
    verify_tls: bool = True
    grpc_tls: bool = True
    grpc_server_name: str | None = None
```

Method:
- `auth_headers() -> dict[str, str]`
  - Always returns `{"content-type": "application/json"}`
  - Adds `x-api-key` when configured

Auth preference notes:
- Unified stream prefers `UNIFIED_STREAM_KEY`, then falls back to `HYPER_API_KEY`
- gRPC MCP/status wiring can use `ALEATORIC_GRPC_KEY` and `HYPER_STATUS_TOKEN`

## 2.2 `GrpcConnectionConfig`
File: `hypercore_sdk/grpc_client.py`

```python
@dataclass(slots=True)
class GrpcConnectionConfig:
    target: str
    timeout_s: float = 5.0
    use_tls: bool = True
    server_name: str | None = None
    api_key: str | None = None
    ca_cert_path: str | None = None
```

## 3. `HyperCoreAPI` Interface (High-Value `/info` + JSON-RPC)

File: `hypercore_sdk/api.py`

Design:
- Reuses one `httpx.Client` for connection pooling and lower tail latency.
- Supports context manager usage (`with HyperCoreAPI(...) as api:`).
- Separates raw calls from typed wrappers and derived analytics.

### 3.1 Lifecycle and Raw Calls

| Method | Purpose | Request | Return |
|---|---|---|---|
| `close()` | Close owned HTTP client | none | `None` |
| `rpc_call(method, params=None, request_id=1)` | Raw JSON-RPC call | POST `rpc_url` JSON-RPC payload | `result` field |
| `info_call(info_type, **kwargs)` | Raw Hyperliquid `/info` call | POST `info_url` with `{"type": info_type, ...}` | Raw decoded JSON |
| `block_number()` | Convenience block height | `rpc_call("eth_blockNumber")` | `int` |

### 3.2 Market Data Wrappers

| Method | `/info type` | Return shape |
|---|---|---|
| `all_mids(dex="")` | `allMids` | `dict[str, str]` |
| `coin_mid(coin, dex="")` | `allMids` | `float` |
| `meta(dex="")` | `meta` | `dict[str, Any]` |
| `spot_meta()` | `spotMeta` | `dict[str, Any]` |
| `meta_and_asset_ctxs()` | `metaAndAssetCtxs` | `(meta_dict, list[asset_ctx_dict])` |
| `spot_meta_and_asset_ctxs()` | `spotMetaAndAssetCtxs` | `(spot_meta_dict, list[spot_asset_ctx_dict])` |
| `l2_snapshot(coin)` | `l2Book` | `dict[str, Any]` |
| `candles_snapshot(coin, interval, start_time_ms, end_time_ms)` | `candleSnapshot` | `list[dict[str, Any]]` |
| `funding_history(coin, start_time_ms, end_time_ms=None)` | `fundingHistory` | `list[dict[str, Any]]` |

### 3.3 User/Account Wrappers

| Method | `/info type` | Return shape |
|---|---|---|
| `user_state(address, dex="")` | `clearinghouseState` | `dict[str, Any]` |
| `spot_user_state(address)` | `spotClearinghouseState` | `dict[str, Any]` |
| `open_orders(address, dex="")` | `openOrders` | `list[dict[str, Any]]` |
| `frontend_open_orders(address, dex="")` | `frontendOpenOrders` | `list[dict[str, Any]]` |
| `user_fills(address)` | `userFills` | `list[dict[str, Any]]` |
| `user_fills_by_time(address, start_time_ms, end_time_ms=None, aggregate_by_time=False)` | `userFillsByTime` | `list[dict[str, Any]]` |
| `portfolio(address)` | `portfolio` | `dict[str, Any]` |
| `user_non_funding_ledger_updates(address, start_time_ms, end_time_ms=None)` | `userNonFundingLedgerUpdates` | `list[dict[str, Any]]` |
| `historical_orders(address)` | `historicalOrders` | `list[dict[str, Any]]` |
| `user_twap_slice_fills(address)` | `userTwapSliceFills` | `list[dict[str, Any]]` |
| `user_vault_equities(address)` | `userVaultEquities` | `list[dict[str, Any]]` |
| `user_role(address)` | `userRole` | `dict[str, Any]` |
| `user_rate_limit(address)` | `userRateLimit` | `dict[str, Any]` |

### 3.4 Derived Intelligence

| Method | Description | Return schema |
|---|---|---|
| `top_of_book(coin)` | Best bid/ask, spread, spread bps from L2 | `{best_bid, best_ask, mid, spread, spread_bps}` |
| `orderbook_imbalance(coin, depth=5)` | Bid/ask notional and normalized imbalance | `{bid_notional, ask_notional, imbalance, depth}` |
| `asset_ctx(coin)` | Resolve coin asset context from `metaAndAssetCtxs` | `dict[str, Any]` |
| `market_snapshot(coin)` | Composite market view | `{coin, mid_px, top_of_book, orderbook_imbalance, asset_ctx}` |
| `summarize_fills(fills)` | Fill aggregates | `{fills, total_notional, total_size, latest_fill_ms, by_coin}` |
| `user_flow_snapshot(address, dex="")` | User state + open orders + fills summary | `{address, user_state, open_orders, fill_summary}` |
| `summarize_funding_history(records)` | Funding aggregate stats | `{count, avg_funding_rate, min_funding_rate, max_funding_rate, latest_time_ms}` |
| `funding_snapshot(coin, start_time_ms, end_time_ms=None)` | Funding rows + stats + window | `{coin, window, summary, rows}` |
| `summarize_non_funding_ledger_updates(updates)` | Ledger update counts by type | `{count, by_type, latest_time_ms}` |
| `user_activity_snapshot(address, start_time_ms, end_time_ms=None, dex="")` | Composite user activity | `{address, window, user_state, fills, fills_summary, ledger_updates, ledger_summary}` |

## 4. Dedicated Unified Stream Interface

File: `hypercore_sdk/unified_stream.py`

`UnifiedStreamClient` reads from pre-decoded stream endpoints using `x-api-key` auth when configured.
It prefers `UNIFIED_STREAM_KEY` over the generic `HYPER_API_KEY`.

| Method | Endpoint | Return |
|---|---|---|
| `stats()` | `GET /api/v1/unified/stats` | `dict[str, Any]` |
| `events(limit=200, event_type=None, stream=None)` | `GET /api/v1/unified/events?...` | `dict[str, Any]` |
| `consensus_pulse()` | `GET /api/v1/unified/consensus-pulse` | `dict[str, Any]` |
| `all_mids(dex="")` | `GET /api/v1/unified/all-mids` | `dict[str, Any]` |
| `l2_book(coin, dex="", depth=None)` | `GET /api/v1/unified/l2-book` | `dict[str, Any]` |
| `asset_contexts(coin=None, dex="")` | `GET /api/v1/unified/asset-contexts` | `dict[str, Any]` |
| `sse_events(max_events=20)` | `GET /api/v1/unified/stream` (SSE) | `Generator[dict[str, Any], None, None]` |
| `sse_all_mids(dex="", max_events=20)` | `GET /api/v1/unified/all-mids/stream` (SSE) | `Generator[dict[str, Any], None, None]` |
| `sse_l2_book(coin, dex="", depth=None, max_events=20)` | `GET /api/v1/unified/l2-book/stream` (SSE) | `Generator[dict[str, Any], None, None]` |
| `sse_asset_contexts(coin=None, dex="", max_events=20)` | `GET /api/v1/unified/asset-contexts/stream` (SSE) | `Generator[dict[str, Any], None, None]` |

`sse_events()` behavior:
- Parses `data:` lines only
- JSON-decodes each event payload
- Yields only object payloads (`dict`)
- Stops after `max_events`

New browser-safe unified surfaces:
- `all_mids()` is the local full-symbol snapshot for price ribbons and multi-symbol dashboards.
- `l2_book()` is the canonical local bid/ask ladder snapshot for order-book depth and imbalance views.
- `asset_contexts()` is the local normalized `metaAndAssetCtxs` view for funding, open interest, mark price, previous day price, and 24h notional volume.

## 4.1 Status API Interface

File: `hypercore_sdk/status.py`

| Method | Endpoint | Return |
|---|---|---|
| `health()` | `GET /healthz` | `dict[str, Any]` |
| `public_status()` | `GET /api/v1/public/status` | `dict[str, Any]` |
| `private_status()` | `GET /api/v1/status` | `dict[str, Any]` |
| `admin_tokens()` | `GET /api/v1/admin/tokens` | `dict[str, Any]` |

`private_status()` and `admin_tokens()` use `HYPER_STATUS_TOKEN` when configured.

## 4.2 MCP Interface

Files:
- `hypercore_sdk/mcp.py`
- `hypercore_sdk/mcp_cli.py`

Console entrypoint:
- `hypercore-sdk-mcp`

Current MCP tools:
- `catalog_interfaces`
- `grpc_get_mid_price`
- `grpc_stream_mids_sample`
- `grpc_get_block_number`
- `grpc_stream_liquidations_sample`
- `unified_get_stats`
- `unified_get_events`
- `unified_get_consensus_pulse`
- `unified_get_all_mids`
- `unified_get_l2_book`
- `unified_get_asset_contexts`
- `status_get_public`
- `status_get_private`
- `rpc_call`

## 5. WebSocket Interface

File: `hypercore_sdk/ws.py`

### 5.1 `get_price_from_ws(...)`
```python
async def get_price_from_ws(
    *,
    ws_url: str,
    coin: str = "BTC",
    subscription_type: str = "allMids",  # allMids | trades | l2Book
    timeout_s: float = 10.0,
    api_key: str | None = None,
) -> dict[str, Any]
```

Return:
```json
{
  "coin": "BTC",
  "price": 65000.1,
  "channel": "allMids|trades|l2Book",
  "latency_ms": 12.345,
  "message": {"...": "raw ws frame"}
}
```

## 6. gRPC Interface

File: `hypercore_sdk/grpc_client.py`

### 6.1 Service-Level Methods

| Method | Description | Return schema |
|---|---|---|
| `health_check(service="")` | gRPC health probe | `{status, latency_ms}` |
| `list_services()` | gRPC reflection list | `list[str]` |
| `get_mid_price(coin="BTC")` | Price service unary call | `{coin, price, ts_ms, source, channel, latency_ms}` |
| `get_block_number()` | Block number unary call | `{hex, number, ts_ms, latency_ms}` |
| `stream_mids(coin="BTC", subscription="allMids", heartbeat_s=10, max_messages=10)` | Streaming mids | `list[{coin, price, ts_ms, source, channel}]` |

### 6.2 Diagnostics

| Method | Description | Return schema |
|---|---|---|
| `grpcurl_invoke(...)` | Invoke via local `grpcurl` binary | `{command, returncode, stdout, stderr}` |

## 7. Speed Test Utilities

File: `hypercore_sdk/speed.py`

| Function | Description | Return |
|---|---|---|
| `run_rpc_speed_test(api, count=30)` | Repeated `eth_blockNumber` calls | `{stats, ok, failed, errors}` |
| `run_ws_speed_test(..., count=10)` | Repeated WS connect+first-price | `{stats, ok, failed, errors}` |
| `run_grpc_health_speed_test(grpc_client, count=20, service="")` | Repeated gRPC health probes | `{stats, ok, failed, errors}` |

`stats` schema comes from `LatencyStats.as_dict()`:
```json
{
  "count": 10,
  "min_ms": 3.1,
  "p50_ms": 4.2,
  "p95_ms": 6.7,
  "max_ms": 7.0,
  "avg_ms": 4.6
}
```

## 8. CLI Interface Matrix

Entrypoint: `hypercore-sdk`

Top-level commands:
- `price` - price helpers (`ws`, `info`)
- `intel` - derived analytics (`market`, `user-flow`, `fills`, `funding`, `activity`)
- `rpc` - generic JSON-RPC (`call`)
- `stream` - dedicated unified stream (`stats`, `events`, `sse`)
- `grpc` - gRPC diagnostics/data (`health`, `list-services`, `invoke`, `setup-template`, `price`, `stream`, `block-number`)
- `speed` - speed tests (`rpc`, `ws`, `grpc-health`)

Examples:
```bash
hypercore-sdk stream stats
hypercore-sdk stream events --limit 100
hypercore-sdk stream sse --max-events 10
hypercore-sdk intel market --coin BTC
hypercore-sdk grpc health --target hl.grpc.aleatoric.systems:443
```

## 9. Error Model

Expected raised exceptions:
- `RuntimeError`: semantic/shape validation failures, SDK-level contract mismatch
- `httpx` exceptions: transport-level HTTP failures
- `grpc` exceptions: gRPC call/channel failures
- `ValueError`: CLI input validation errors

Design intent:
- Fail fast on schema mismatch
- Preserve upstream errors for diagnosis

## 10. Astro Indexing Guidance

Recommended indexing units:
- Method catalogs in sections 3.2, 3.3, 3.4, 4, 6.1, 7, 8
- Derived schema section (market snapshot, funding snapshot, user activity snapshot)
- Quality/limits section
