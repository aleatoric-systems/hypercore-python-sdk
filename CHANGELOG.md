# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] — 2026-03-13

### Added
- Browser-safe unified client parity for:
  - `all_mids()` / `sse_all_mids()`
  - `l2_book()` / `sse_l2_book()`
  - `asset_contexts()` / `sse_asset_contexts()`
- Unified `consensus_pulse()` client method.
- Status API client:
  - `hypercore_sdk/status.py`
- Python stdio MCP server:
  - `hypercore_sdk/mcp.py`
  - `hypercore_sdk/mcp_cli.py`
- Tests for unified snapshot/SSE parity, status client, and MCP server:
  - `tests/test_unified_stream.py`
  - `tests/test_status.py`
  - `tests/test_mcp.py`
  - `tests/test_cli.py`
- Dedicated liquidation support in client and examples (`StreamLiquidations` path), plus unified `liquidation_cascade` helpers and MCP passthrough.
- Provider matrix benchmark option for liquidation feed benchmarking.
- Project tracking docs:
  - `PROJECT_STATE.md`
  - `AGENTS.md`
- Container deployment artifacts:
  - `Dockerfile`
  - `docker-compose.yml`
  - `DEPLOYMENT.md`
- Auth/key-scope preflight utility: `examples/preflight_feed_auth.py` for rpc/unified/disk-ws/grpc validation.
- Provider benchmark JSON template now includes scoped key wiring guidance for gRPC vs unified/disk streams.
- Live gRPC console example for side-by-side `l2Book` and `trades` bridge feeds (`examples/grpc_l2book_trades_console.py`).

### Changed
- `hypercore_sdk/cli.py` now exposes unified commands for `consensus-pulse`, `all-mids`, `l2-book`, `asset-contexts`, `liquidations`, and `cascades`.
- README and API reference now document the Python MCP server and the browser-safe unified interfaces.
- Unified stream client query construction was cleaned up to remove repeated ad hoc param-building paths while keeping request semantics unchanged.
- Feed benchmark split between market WS and disk-sync WS.
- README setup/troubleshooting now documents virtualenv-first install flow.
- `.gitignore` expanded for coverage, caches, local outputs, and egg metadata.
- Default endpoint targets updated to Aleatoric stream infrastructure:
  - Market/disk WS default `wss://disk.grpc.aleatoric.systems/`
  - Unified API default `https://unified.grpc.aleatoric.systems`
  - gRPC default `hl.grpc.aleatoric.systems:443`
- Feed latency benchmark now records per-attempt audit stamps, metric-kind summaries, and event-age stats where source timestamps exist.
- Key selection hardened across feed benchmark, matrix runner, and preflight script to ignore malformed placeholder keys and prefer RPC-scoped keys for gRPC checks.
- Provider benchmark and auth preflight output now make scoped endpoint auth failures explicit, reducing false attribution of partial-provider results to latency regressions.
- Example credential loading and scoped key selection are now centralized in `hypercore_sdk/example_auth.py`, removing drift across benchmark, preflight, provider-matrix, and gRPC live examples.
- Benchmark and preflight HTTP checks now classify upstream `502/503/504` responses as `upstream_unavailable`, and feed benchmark output now includes `auth_key_sources` plus `availability_alerts`.
- Feed benchmark output is now typed via `hypercore_sdk/benchmark_models.py`, supports `--profile-json` / `--out-json`, ships reproducible benchmark profiles plus March 10, 2026 baseline snapshots, and can emit machine-readable availability exit codes.
- `examples/grpc_l2book_trades_console.py` now:
  - reports which key source it selected
  - runs gRPC health and `PriceService` preflight before streaming
  - renders compact gRPC auth-preflight failures instead of raw `_InactiveRpcError` blobs
  - fails fast with a clear diagnosis when `PriceService` access returns `403/PERMISSION_DENIED`, including the broader case where health and stream RPCs are both denied by the endpoint
- gRPC live examples now prefer `ALEATORIC_GRPC_KEY` and RPC-scoped keys before `GRPC_STREAM_KEY` / `UNIFIED_STREAM_KEY`, fixing false `403` failures in mixed-key environments.
- README and project-state docs now explain how to distinguish local key-selection drift from endpoint-side gRPC authorization failures.
- README and deployment docs now formalize the containerized SDK runtime/build model and explicitly scope out the external bridge server.
- CI and release automation now run tests, mypy, package builds, and `twine check` for push/PR validation and tagged releases.
- CI now also builds Docker `runtime`/`dev` targets, validates `docker-compose.yml`, runs a containerized CLI smoke, and tagged releases publish the runtime image to GHCR.
- `AGENTS.md` now requires packaging validation alongside the existing gRPC local-vs-endpoint auth verification rules.

## [0.3.0] - 2026-03-08

### Added
- Read-only SDK architecture for RPC, WS, gRPC, unified stream, and high-value info surfaces.
- CLI command groups for `price`, `intel`, `rpc`, `stream`, `grpc`, and `speed`.
- Example scripts for auth preflight, latency benchmarking, and live stream consumers.
