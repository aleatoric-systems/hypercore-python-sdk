# Changelog

All notable changes to this project are documented in this file.

## [Unreleased] - 2026-03-09

### Added
- Dedicated liquidation support in client and examples (`StreamLiquidations` path).
- Provider matrix benchmark option for liquidation feed benchmarking.
- Project tracking docs:
  - `PROJECT_STATE.md`
  - `AGENTS.md`
- Auth/key-scope preflight utility: `examples/preflight_feed_auth.py` for rpc/unified/disk-ws/grpc validation.
- Provider benchmark JSON template now includes scoped key wiring guidance for gRPC vs unified/disk streams.
- Live gRPC console example for side-by-side `l2Book` and `trades` bridge feeds (`examples/grpc_l2book_trades_console.py`).

### Changed
- Feed benchmark split between market WS and disk-sync WS.
- README setup/troubleshooting now documents virtualenv-first install flow.
- `.gitignore` expanded for coverage, caches, local outputs, and egg metadata.
- Default endpoint targets updated to Aleatoric stream infrastructure:
  - Market/disk WS default `wss://disk.grpc.aleatoric.systems/`
  - Unified API default `https://unified.grpc.aleatoric.systems`
  - gRPC default `hl.grpc.aleatoric.systems:443`
- Feed latency benchmark now records per-attempt audit stamps, metric-kind summaries, and event-age stats where source timestamps exist.
- Key selection hardened across feed benchmark, matrix runner, and preflight script to ignore malformed placeholder keys and prefer RPC-scoped keys for gRPC checks.
- `examples/grpc_l2book_trades_console.py` now:
  - reports which key source it selected
  - runs a gRPC health preflight before streaming
  - renders compact gRPC auth-preflight failures instead of raw `_InactiveRpcError` blobs
  - fails fast with a clear diagnosis when `PriceService` stream methods return `403/PERMISSION_DENIED`, including the broader case where health and stream RPCs are both denied by the endpoint
- `AGENTS.md` now requires explicit local-vs-endpoint auth verification when gRPC example diagnostics change.

## [0.3.0] - 2026-03-08

### Added
- Read-only SDK architecture for RPC, WS, gRPC, unified stream, and high-value info surfaces.
- CLI command groups for `price`, `intel`, `rpc`, `stream`, `grpc`, and `speed`.
- Example scripts for auth preflight, latency benchmarking, and live stream consumers.
