# Changelog

All notable changes to this project are documented in this file.

## [Unreleased] - 2026-03-08

### Added
- Dedicated liquidation support in client and examples (`StreamLiquidations` path).
- Provider matrix benchmark option for liquidation feed benchmarking.
- Project tracking docs:
  - `PROJECT_STATE.md`
  - `AGENTS.md`

### Changed
- Feed benchmark split between market WS and disk-sync WS.
- README setup/troubleshooting now documents virtualenv-first install flow.
- `.gitignore` expanded for coverage, caches, local outputs, and egg metadata.

## [0.3.0] - 2026-03-08

### Added
- Read-only SDK architecture for RPC, WS, gRPC, unified stream, and high-value info surfaces.
- CLI command groups for `price`, `intel`, `rpc`, `stream`, `grpc`, and `speed`.
- Example scripts for auth preflight, latency benchmarking, and live stream consumers.

