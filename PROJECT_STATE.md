# Project State

Last updated: 2026-03-09

## Current Capability

### Data APIs
- JSON-RPC passthrough (read operations)
- Hyperliquid public WS market subscriptions
- gRPC bridge calls:
  - health/reflection
  - mid price and block number
  - stream mids
  - stream liquidations (dedicated method)
- Unified REST/SSE feed access
- Disk-sync WS first-event path in benchmarks

### Tooling
- CLI with typed command groups
- Latency benchmark suite for feed comparison
- Provider matrix benchmark script (Aleatoric vs public vs third-party endpoints)
- Live console examples for public WS ladder+trades and gRPC `l2Book`+`trades` feeds
- gRPC console now shows selected key source and distinguishes:
  - health success + stream authorization denial
  - health authorization denial + stream authorization denial
- Test suite with coverage gate (>=90%)

## Known Operational Risks

1. Environment drift:
   - Running a global `hypercore-sdk` shim can bypass repo state and fail imports.
   - Mitigation: always use `.venv` and validate `which hypercore-sdk`.
2. Endpoint configuration drift:
   - Incorrect WS host mapping can produce misleading benchmark results.
   - Mitigation: keep market WS and disk-sync WS explicitly separated in benchmark args.
3. Rate-limit variability:
   - Unified endpoints may return `429` under bursty test runs.
   - Mitigation: use configurable pacing/retry flags in benchmark scripts.
4. Endpoint-side gRPC auth divergence:
   - Health/reflection and `PriceService` stream methods may be authorized differently across endpoint deployments.
   - Some endpoints deny both health and stream RPCs with the same `403/PERMISSION_DENIED` response.
   - Mitigation: use the console's preflight diagnosis, and fall back to `examples/orderbook_trades_console.py` for live viewing until the endpoint scope is fixed.
5. Aleatoric RPC availability drift:
   - Benchmark smoke on 2026-03-09 saw `https://rpc.aleatoric.systems/` return `502 Bad Gateway`.
   - Mitigation: treat RPC latency baselines as invalid until the upstream endpoint is healthy again.

## Near-Term Next Work

1. Resolve and document endpoint-side gRPC auth policy so health/reflection and `PriceService` methods use clearly defined key scopes.
2. Investigate the `502 Bad Gateway` response from `https://rpc.aleatoric.systems/` observed during benchmark smoke on 2026-03-09.
3. Add CI workflow for tests + mypy + packaging checks.
4. Add reproducible benchmark profiles and baseline result snapshots.
5. Add typed response models for benchmark output JSON.
6. Add release automation (`build`, `twine check`, version tagging flow).
