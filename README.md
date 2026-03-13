# Hypercore Python SDK

![MCP Server Included](https://img.shields.io/badge/MCP-server%20included-2ea043)

Python SDK and CLI for:
- JSON-RPC access
- WebSocket market data
- gRPC bridge access
- Dedicated unified stream endpoints (pre-decoded event feed, browser-safe allMids, L2 book, asset contexts)
- Status API access
- Stdio MCP server built on top of the SDK clients
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

## Dockerized Runtime

This repo can be containerized for the SDK, CLI, examples, benchmarks, and package-build flow. The external Aleatoric bridge service is not part of this repo and is not deployed by these containers.

Build the images:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
docker build --target runtime -t hypercore-sdk:runtime .
docker build --target dev -t hypercore-sdk:dev .
```

Run common flows with [docker-compose.yml](docker-compose.yml):

```bash
docker compose run --rm cli --help
docker compose --env-file .env run --rm ws-console
docker compose --env-file .env run --rm grpc-console --coin BTC --max-events 20
docker compose --env-file .env run --rm benchmark --coin BTC --runs 5 --skip-unified
docker compose run --rm validate
docker compose run --rm package
```

If the gRPC target requires VPN reachability, connect the VPN before starting the container. Docker Desktop must be able to pass container traffic over that VPN path or gRPC will fail with `StatusCode.UNAVAILABLE`.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full container/runtime model.

## Quality Gates

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
pytest
mypy -p hypercore_sdk
python -m build
python -m twine check dist/*
```

Current validation status for the checked-in implementation:

- `pytest`: `127 passed`
- coverage gate: `92.45%`
- `mypy -p hypercore_sdk`: clean
- `python -m build`: passed
- `python -m twine check dist/*`: passed

Coverage output is written to `coverage.xml`.
GitHub Actions now runs the same validation on push/PR, and tagged `v*` releases build artifacts and publish a GitHub release.
Push/PR CI now also builds the Docker `runtime` and `dev` targets, validates `docker-compose.yml`, and runs a containerized CLI smoke. Tagged `v*` releases also publish the runtime image to `ghcr.io/<repo-owner>/hypercore-python-sdk:<tag>`.

## Project Tracking Docs

- `CHANGELOG.md` - released changes and migration notes.
- `PROJECT_STATE.md` - current implementation status and open gaps.
- `AGENTS.md` - agent workflow and handoff conventions for this repo.
- `DEPLOYMENT.md` - containerized runtime/build model and environment boundary.

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
hypercore-sdk stream consensus-pulse
hypercore-sdk stream all-mids
hypercore-sdk stream l2-book --coin BTC --depth 5
hypercore-sdk stream asset-contexts --coin BTC
```

Python access:

```python
from hypercore_sdk import SDKConfig, UnifiedStreamClient

cfg = SDKConfig(unified_stream_url="https://unified.grpc.aleatoric.systems", api_key="<readonly-key>")
with UnifiedStreamClient(cfg) as stream:
    print(stream.stats())
    print(stream.events(limit=50))
    print(stream.all_mids())
    print(stream.l2_book("BTC", depth=5))
    print(stream.asset_contexts(coin="BTC"))
    for event in stream.sse_events(max_events=5):
        print(event)
```

## Status API

```python
from hypercore_sdk import SDKConfig, StatusClient

cfg = SDKConfig(status_url="http://127.0.0.1:8090", status_token="<status-token>")
with StatusClient(cfg) as status:
    print(status.public_status())
    print(status.private_status())
```

## Python MCP

The Python SDK now ships a stdio MCP server built on top of the SDK clients.

Install the dev environment first, then run:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
source .venv/bin/activate
hypercore-sdk-mcp
```

Quick stdio smoke test:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | hypercore-sdk-mcp
```

Key env vars:

- `HYPER_GRPC_TARGET`
- `ALEATORIC_GRPC_KEY`
- `HYPER_UNIFIED_STREAM_URL`
- `UNIFIED_STREAM_KEY`
- `HYPER_RPC_URL`
- `HYPER_API_KEY`
- `HYPER_STATUS_URL`
- `HYPER_STATUS_TOKEN`

The MCP server exposes:

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

# Reproducible profiles + checked-in baselines
python3 examples/feed_latency_examples.py \
  --profile-json examples/benchmark_profiles/aleatoric_market_ws.json \
  --out-json examples/benchmark_baselines/aleatoric_market_ws.latest.json

python3 examples/feed_latency_examples.py \
  --profile-json examples/benchmark_profiles/aleatoric_grpc_core.json \
  --availability-exit-codes
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
The benchmark output now also includes `auth_key_sources`, `availability_alerts`, and `exit_recommendation`, so upstream HTTP `502/503/504` failures are surfaced as `upstream_unavailable` instead of generic latency regressions.
Shipped profiles live in `examples/benchmark_profiles/`, and checked-in March 10, 2026 baseline snapshots live in `examples/benchmark_baselines/`.

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
- the `PriceService` preflight result

If the endpoint allows health checks but rejects `PriceService`, the console now fails before starting the
live stream workers and prints:
- a fast diagnosis: `health works, PriceService auth denied by endpoint; streams will fail`

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

All example scripts auto-load credentials from `api/.env` first, then `.env` in the repo root, and accept either `API_KEY` or `HYPER_API_KEY`. The gRPC examples prefer RPC-scoped keys before unified-stream fallbacks, and the preflight/benchmark scripts now classify upstream HTTP outages separately from auth failures. `--availability-exit-codes` enables state-specific exit codes for automation.
