# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-03-13

### Added

- Public package metadata for Python distribution, including license, authors, URLs, classifiers, and package manifest controls.
- Customer-facing documentation, contribution guide, and a basic connection example.
- Refreshed API interface reference for external consumers and support handoff.
- Branded GitHub-facing README assets, discoverability keywords, and production documentation.
- GitHub Actions workflows for CI and tagged releases.
- Browser-safe unified stream parity for all-mids, L2 book, and asset contexts.
- Status API client, stdio MCP server, and expanded test coverage.

### Changed

- Reframed the repository as a public Aleatoric Systems SDK for external customers.
- Standardized release validation around `pytest`, `mypy`, `python -m build`, and `twine check`.
- Rewrote the README around installation, authentication, examples, release flow, and support.
- Expanded MCP tests to treat the published tool matrix as a contract.

## [0.2.0] - 2026-03-08

### Added

- Read-only SDK architecture for RPC, WebSocket, gRPC, unified stream, and higher-level info surfaces.
- CLI commands for `price`, `intel`, `rpc`, `stream`, `grpc`, and `speed`.
- Example scripts for auth preflight, live streams, and benchmark workflows.
