# Project State

Last updated: 2026-03-10

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
- gRPC examples now prefer RPC-scoped keys before unified-stream fallbacks
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
4. Mixed-key gRPC auth drift:
   - Environments that export both RPC-scoped and unified-stream keys can select the wrong key class and produce misleading `403/PERMISSION_DENIED` results.
   - Some endpoint deployments may also authorize health/reflection and `PriceService` stream methods differently.
   - Mitigation: gRPC examples now prefer `ALEATORIC_GRPC_KEY`, then RPC-scoped keys; inspect `key_source` and the console preflight diagnosis before blaming the endpoint.
5. Aleatoric RPC availability drift:
   - Benchmark smoke on 2026-03-10 again saw `https://rpc.aleatoric.systems/` return `502 Bad Gateway`.
   - Mitigation: treat RPC latency baselines as invalid until the upstream endpoint is healthy again.

## Near-Term Next Work

1. Extract shared gRPC example key-selection/auth-diagnostics helpers so console, liquidation, and preflight tools cannot drift.
2. Investigate the `502 Bad Gateway` response from `https://rpc.aleatoric.systems/` observed again during benchmark smoke on 2026-03-10.
3. Add CI workflow for tests + mypy + packaging checks.
4. Add reproducible benchmark profiles and baseline result snapshots.
5. Add typed response models for benchmark output JSON.
6. Add release automation (`build`, `twine check`, version tagging flow).
