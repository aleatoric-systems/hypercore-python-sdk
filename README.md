# Hypercore Python SDK

Python SDK and CLI for:
- JSON-RPC access
- WebSocket market data
- gRPC bridge access
- Dedicated unified stream endpoints (pre-decoded event feed)
- High-value market/user intelligence from `/info` (L2, funding, fills, portfolio, user flow)

This SDK is read-only/data-plane only. Signing and order placement interfaces are intentionally excluded.

## Install

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
which hypercore-sdk
python -c "import hypercore_sdk; print(hypercore_sdk.__file__)"
```

## Development Setup

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## Quality Gates

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
pytest
mypy -p hypercore_sdk
python -m build
python -m twine check dist/*
```

Coverage output is written to `coverage.xml`.
GitHub Actions now runs the same validation on push/PR, and tagged `v*` releases build artifacts and publish a GitHub release.

## Project Tracking Docs

- `CHANGELOG.md` - released changes and migration notes.
- `PROJECT_STATE.md` - current implementation status and open gaps.
- `AGENTS.md` - agent workflow and handoff conventions for this repo.

## Troubleshooting

If you see:

```text
ModuleNotFoundError: No module named 'hypercore_sdk'
```

you are usually running a global shim (`/Users/jaws/.pyenv/.../bin/hypercore-sdk`) instead of this repo's virtualenv.

Fix:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
hash -r
which hypercore-sdk
hypercore-sdk --help
```

Expected `which hypercore-sdk` output:

```text
/Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk/.venv/bin/hypercore-sdk
```

## High-Value Intel Surfaces

`HyperCoreAPI` exposes direct convenience methods for indexers and analytics:
- `market_snapshot(coin)` (mid, top-of-book, asset context)
- `user_flow_snapshot(address, dex="")` (state, open orders, fill summary)
- `user_fills`, `user_fills_by_time`, `funding_history`, `portfolio`
- `historical_orders`, `user_non_funding_ledger_updates`, `user_vault_equities`, `user_rate_limit`

```python
from hypercore_sdk import HyperCoreAPI, SDKConfig

with HyperCoreAPI(SDKConfig(info_url="https://api.hyperliquid.xyz/info")) as api:
    market = api.market_snapshot("BTC")
    flow = api.user_flow_snapshot("0xYourAddress")
    print(market["top_of_book"])
    print(flow["fill_summary"])
```

CLI shortcuts:

```bash
hypercore-sdk intel market --coin BTC
hypercore-sdk intel user-flow --address 0xYourAddress
hypercore-sdk intel fills --address 0xYourAddress --start-time-ms 1700000000000 --end-time-ms 1700003600000
```

## Dedicated Unified Stream

Set your stream gateway URL:

```bash
export HYPER_UNIFIED_STREAM_URL="https://unified.grpc.aleatoric.systems"
export HYPER_API_KEY="<readonly-key>"
```

CLI access:

```bash
hypercore-sdk stream stats
hypercore-sdk stream events --limit 100
hypercore-sdk stream sse --max-events 10
```

Python access:

```python
from hypercore_sdk import SDKConfig, UnifiedStreamClient

cfg = SDKConfig(unified_stream_url="https://unified.grpc.aleatoric.systems", api_key="<readonly-key>")
with UnifiedStreamClient(cfg) as stream:
    print(stream.stats())
    print(stream.events(limit=50))
    for event in stream.sse_events(max_events=5):
        print(event)
```

## Example Apps

These runnable scripts are in `examples/`:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
```

Benchmark available feeds and latency:

```bash
python3 examples/preflight_feed_auth.py
python3 examples/feed_latency_examples.py --coin BTC --runs 5 \
  --rpc-key "$RPC_GATEWAY_KEY" \
  --grpc-key "$RPC_GATEWAY_KEY" \
  --grpc-include-liquidations \
  --ws-url "wss://api.hyperliquid.xyz/ws" \
  --ws-key "" \
  --disk-ws-url "wss://disk.grpc.aleatoric.systems/" \
  --disk-ws-key "$UNIFIED_STREAM_KEY" \
  --unified-key "$UNIFIED_STREAM_KEY" \
  --ws-max-size none \
  --unified-min-interval-ms 700 \
  --unified-retry-429 1
```

Multi-provider comparison (Aleatoric vs public vs HyperRPC vs Dwellir):

```bash
# Option A: use env-driven defaults
python3 examples/provider_benchmark_matrix.py --coin BTC --runs 5 --out-json provider_matrix.json

# Option B: explicit provider config
python3 examples/provider_benchmark_matrix.py \
  --providers-json examples/providers.example.json \
  --coin BTC \
  --runs 5 \
  --grpc-include-liquidations \
  --out-json provider_matrix.json
```

`examples/providers.example.json` now contains only live baseline endpoints (Aleatoric + Hyperliquid public).
Aleatoric gRPC examples now prefer `ALEATORIC_GRPC_KEY`, then RPC-scoped keys (`RPC_GATEWAY_KEY`, `RPC_KEY`, `HYPER_API_KEY`), and only fall back to `GRPC_STREAM_KEY` / `UNIFIED_STREAM_KEY` for legacy deployments.
If `--grpc-include-liquidations` is enabled but bridge liquidation topics are not configured, that check is reported as skipped (not a provider failure).
The benchmark output now also includes `auth_key_sources` and `availability_alerts`, so upstream HTTP `502/503/504` failures are surfaced as `upstream_unavailable` instead of generic latency regressions.

Live orderbook ladder + trades console app:

```bash
python3 examples/orderbook_trades_console.py --coin BTC --depth 12 --trade-limit 30
```

Live gRPC `l2Book` + `trades` bridge console:

```bash
python3 examples/grpc_l2book_trades_console.py --coin BTC --history-limit 30
```

This gRPC console renders the latest normalized bridge prices from `subscription=l2Book` and
`subscription=trades` side-by-side. Use `examples/orderbook_trades_console.py` when you need the
full public WebSocket depth ladder instead of the bridge's normalized feed output.

The gRPC console now always prints:
- the selected key source
- the health preflight result

If the endpoint allows health checks but rejects `PriceService` streams, the console also prints:
- a fast diagnosis: `health works, stream auth denied by endpoint`

If the endpoint rejects health and stream RPCs with the same key, it prints:
- `health=auth_denied | StatusCode.PERMISSION_DENIED | Received http2 header with status: 403`
- a fast diagnosis: `health and stream auth denied by endpoint`

That broader denial can indicate endpoint-side key scope/gateway policy or a local mixed-key env selecting the wrong key class. Check `key_source` first; the gRPC examples now prefer RPC-scoped keys before unified-stream fallbacks.

In either case, use `examples/orderbook_trades_console.py` for live viewing until the endpoint-side gRPC scope is corrected.

Live liquidation stream from gRPC feeds:

```bash
python3 examples/grpc_liquidations_live.py --coin BTC --max-events 20
```

CLI equivalent:

```bash
hypercore-sdk grpc liquidations --coin BTC --max-messages 20
```

All example scripts auto-load credentials from `api/.env` first, then `.env` in the repo root, and accept either `API_KEY` or `HYPER_API_KEY`. The gRPC examples prefer RPC-scoped keys before unified-stream fallbacks, and the preflight/benchmark scripts now classify upstream HTTP outages separately from auth failures.
