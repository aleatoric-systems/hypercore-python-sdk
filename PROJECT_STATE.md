# Project State

Last updated: 2026-03-08

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

## Near-Term Next Work

1. Add CI workflow for tests + mypy + packaging checks.
2. Add reproducible benchmark profiles and baseline result snapshots.
3. Add typed response models for benchmark output JSON.
4. Add release automation (`build`, `twine check`, version tagging flow).

