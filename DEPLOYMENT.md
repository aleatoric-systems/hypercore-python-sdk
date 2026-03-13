# Deployment Model

This repository can be containerized end-to-end for the SDK, CLI, examples, benchmarks, and package build flow.

It does not contain the upstream Aleatoric bridge server itself. The containerized surface here is:

- `hypercore-sdk` CLI
- runnable example scripts in `examples/`
- benchmark and preflight tooling
- Python package build and validation

It does not deploy:

- the Hyperliquid public WebSocket service
- the Aleatoric gRPC bridge service
- any signing, trading, or custody infrastructure

## Images

The repo now ships a multi-stage [Dockerfile](Dockerfile):

- `runtime`: installs the package and exposes `hypercore-sdk`
- `dev`: adds test/build tooling for `pytest`, `mypy`, `build`, and `twine`

GitHub Actions CI now builds both targets on push/PR, and tagged releases publish the `runtime` image to GHCR.

Build locally:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
docker build --target runtime -t hypercore-sdk:runtime .
docker build --target dev -t hypercore-sdk:dev .
```

## Runtime Configuration

Do not bake secrets into the image. Pass them at runtime with shell environment or `docker compose --env-file .env ...`.

Relevant variables include:

- `ALEATORIC_GRPC_TARGET`
- `ALEATORIC_GRPC_SERVER_NAME`
- `ALEATORIC_GRPC_KEY`
- `RPC_GATEWAY_KEY`
- `RPC_KEY`
- `HYPER_API_KEY`
- `ALEATORIC_MARKET_WS_KEY`
- `UNIFIED_STREAM_KEY`

The example scripts still honor the same key alias logic implemented in [hypercore_sdk/example_auth.py](hypercore_sdk/example_auth.py).

## Compose Services

[docker-compose.yml](docker-compose.yml) formalizes the common flows:

- `cli`: run arbitrary `hypercore-sdk` commands
- `ws-console`: live public WebSocket ladder + trades console
- `grpc-console`: live gRPC `l2Book` + `trades` console
- `benchmark`: feed latency benchmark with JSON output written to `./artifacts`
- `validate`: repo quality gates inside the `dev` image
- `package`: build wheel/sdist into `./dist`

Examples:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk

docker compose run --rm cli price ws --coin BTC

docker compose --env-file .env run --rm ws-console

docker compose --env-file .env run --rm grpc-console --coin BTC --max-events 20

docker compose --env-file .env run --rm benchmark --coin BTC --runs 5 --skip-unified

docker compose run --rm validate

docker compose run --rm package
```

## Network Boundary

These containers are outbound-only clients. No inbound ports are required.

If the gRPC endpoint is only reachable over VPN, the host VPN must already be connected before starting the container. On Docker Desktop, verify that container traffic can traverse the VPN; otherwise `grpc-console` will fail with `StatusCode.UNAVAILABLE` even if the same command works on the host shell.

## Recommended Deployment Pattern

For local/operator use:

1. Build the `runtime` image once.
2. Pass credentials with `docker compose --env-file .env`.
3. Run `grpc-console` or `benchmark` as short-lived jobs.
4. Use `validate` in CI-equivalent checks before publishing package artifacts.

For automation:

1. Keep this image as a client/tooling container.
2. Treat the Aleatoric gRPC bridge and unified feeds as external dependencies.
3. Monitor network/VPN reachability separately from SDK correctness.
