<p align="center">
  <img src="./assets/aleatoric-systems-logo.svg" alt="Aleatoric Systems" width="220">
</p>

# Aleatoric Systems

## Aleatoric MCP Client

![MCP Version](https://img.shields.io/badge/MCP-2024--11--05-0a7f5a)
![License](https://img.shields.io/badge/license-Apache%202.0-1f6feb)
![GitHub last commit](https://img.shields.io/github/last-commit/aleatoric-systems/hypercore-python-sdk)
![MCP Badge](https://img.shields.io/badge/JSON--RPC-2.0-444444)
![Smithery Badge](https://img.shields.io/badge/Smithery-ready-f97316)
![Status](https://img.shields.io/badge/status-production-0a7f5a)
![Compliance](https://img.shields.io/badge/compliance-Aleatoric%20Engine%20API%20v0.5.10-0a7f5a)

Official MCP client SDK for Aleatoric Systems: institutional-grade synthetic market data generation, unified stream access, and operator-ready service tooling.

Verified Compliance: This client is aligned with Aleatoric Engine API `v0.5.10` and MCP Protocol Version `2024-11-05` over JSON-RPC 2.0. The documented examples are validated against the current production endpoint contract.

Keywords: `mcp`, `market-data`, `synthetic-data`, `backtesting`, `trading`, `fintech`, `quantitative-finance`, `perpetuals`, `futures`, `order-book`

## Overview

The Aleatoric Hypercore Python SDK is the public Python and MCP integration surface for Aleatoric Systems. It is designed for customer-facing integrations that need:

- typed JSON-RPC access
- low-latency unified stream access
- browser-safe all-mids, L2 book, and asset-context snapshots
- gRPC diagnostics and bridge consumers
- status monitoring and MCP tooling

This SDK is intentionally read-only. It excludes signing, private key custody, and order placement.

## Features

- JSON-RPC access
- WebSocket market data helpers
- Unified stream access for stats, events, SSE, liquidations, cascades, all-mids, L2 book, and asset contexts
- gRPC diagnostics and bridge consumers
- Status API client
- Stdio MCP server built on the SDK clients
- Example applications and benchmark utilities

## Requirements

- Python 3.10 or later
- `pip` and virtual environment support

## Installation

Install from PyPI when published:

```bash
pip install aleatoric-hypercore-sdk
```

Install from source:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Default Endpoints

- RPC: `https://rpc.aleatoric.systems/`
- Unified stream: `https://unified.grpc.aleatoric.systems`
- gRPC target: `hl.grpc.aleatoric.systems:443`

## Authentication

The SDK supports a general `HYPER_API_KEY`, but scoped credentials are preferred:

- `UNIFIED_STREAM_KEY` for unified stream and disk-sync interfaces
- `ALEATORIC_GRPC_KEY` for gRPC bridge access
- `HYPER_STATUS_TOKEN` for private status endpoints

## Quickstart

### Library connection

```python
from hypercore_sdk import HyperCoreAPI, SDKConfig, UnifiedStreamClient

config = SDKConfig(api_key="your-api-key")

with HyperCoreAPI(config) as api:
    print(api.coin_mid("BTC"))

with UnifiedStreamClient(
    SDKConfig(
        unified_stream_url="https://unified.grpc.aleatoric.systems",
        api_key="your-unified-stream-key",
    )
) as stream:
    print(stream.stats())
```

### CLI connection checks

```bash
hypercore-sdk rpc call --method eth_blockNumber --api-key "$HYPER_API_KEY"
hypercore-sdk price ws --coin BTC --subscription allMids
hypercore-sdk stream stats --api-key "$UNIFIED_STREAM_KEY"
hypercore-sdk grpc health --target hl.grpc.aleatoric.systems:443
```

### MCP server

```bash
export HYPER_GRPC_TARGET="hl.grpc.aleatoric.systems:443"
export ALEATORIC_GRPC_KEY="<grpc-key>"
export HYPER_UNIFIED_STREAM_URL="https://unified.grpc.aleatoric.systems"
export UNIFIED_STREAM_KEY="<unified-key>"
export HYPER_RPC_URL="https://rpc.aleatoric.systems/"
export HYPER_API_KEY="<rpc-key>"

hypercore-sdk-mcp
```

## Production

Production deployment, environment, compliance, and support guidance is documented in [PRODUCTION.md](PRODUCTION.md).

## Examples

- [examples/connection.py](examples/connection.py)
- [examples/preflight_feed_auth.py](examples/preflight_feed_auth.py)
- [examples/feed_latency_examples.py](examples/feed_latency_examples.py)
- [examples/provider_benchmark_matrix.py](examples/provider_benchmark_matrix.py)
- [examples/orderbook_trades_console.py](examples/orderbook_trades_console.py)

Run a basic connection example:

```bash
python examples/connection.py
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
mypy -p hypercore_sdk
python -m build
python -m twine check dist/*
```

## Docker

Build the SDK runtime and dev images:

```bash
docker build --target runtime -t hypercore-sdk:runtime .
docker build --target dev -t hypercore-sdk:dev .
```

Container orchestration examples are documented in [DEPLOYMENT.md](DEPLOYMENT.md).

## Release Process

- CI runs on pushes and pull requests.
- Tags matching `v*` build source and wheel artifacts and publish a GitHub Release.
- Release validation runs `pytest`, `mypy`, `python -m build`, and `python -m twine check`.

## Support

- Email: [github@aleatoric.systems](mailto:github@aleatoric.systems)
- Discord: contact the Aleatoric Systems team for the active customer support server and onboarding channel

## Documentation

- [API_interface.md](API_interface.md)
- [CHANGELOG.md](CHANGELOG.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [PRODUCTION.md](PRODUCTION.md)
- [LICENSE](LICENSE)
