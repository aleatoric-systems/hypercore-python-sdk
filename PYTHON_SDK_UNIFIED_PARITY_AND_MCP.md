# Python SDK Unified Parity And MCP

This document tracks the Python SDK additions required to keep pace with the Hypernode unified-sidecar rollout completed on March 12, 2026.

## Added Unified Client Coverage

The Python `UnifiedStreamClient` now exposes the browser-safe Hypernode surfaces:

- `consensus_pulse()`
- `all_mids(dex="")`
- `l2_book(coin, dex="", depth=None)`
- `asset_contexts(coin=None, dex="")`
- `sse_all_mids(dex="", max_events=20)`
- `sse_l2_book(coin, dex="", depth=None, max_events=20)`
- `sse_asset_contexts(coin=None, dex="", max_events=20)`

These map to:

- `GET /api/v1/unified/consensus-pulse`
- `GET /api/v1/unified/all-mids`
- `GET /api/v1/unified/l2-book`
- `GET /api/v1/unified/asset-contexts`
- and their SSE `/stream` variants

## Added Status Client

The Python SDK now ships `StatusClient` for:

- `health()`
- `public_status()`
- `private_status()`
- `admin_tokens()`

Private/admin calls use `HYPER_STATUS_TOKEN`.

## Added Python MCP

The SDK now ships a stdio MCP server and console entrypoint:

- module: `hypercore_sdk.mcp`
- entrypoint: `hypercore-sdk-mcp`

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

## Validation

Validated in this repo with:

- `pytest`
- `mypy -p hypercore_sdk`
- `python -m build`
- `python -m twine check dist/*`

The parity and MCP additions keep the Python SDK aligned with the TypeScript SDK for the Hypernode-local browser-safe market-data surfaces.
