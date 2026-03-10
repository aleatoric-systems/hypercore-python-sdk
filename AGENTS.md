# AGENTS

This file defines how agents and contributors should operate in this repository.

## Scope

This SDK is **read-only/data-plane**:
- market and chain data access
- performance benchmarking
- stream ingestion helpers

It explicitly excludes:
- signing
- order placement
- private key custody logic

## Working Rules

1. Keep interfaces typed and backwards-compatible where practical.
2. Prefer additive API changes over breaking renames.
3. Update tests for every behavior change.
4. Update `README.md`, `PROJECT_STATE.md`, and `CHANGELOG.md` in the same change.
5. Keep examples runnable from repo root.
6. If a gRPC example changes auth or diagnostics behavior, verify whether failures are caused by local key resolution or endpoint-side authorization before handoff, including mixed-key environments where RPC-scoped and unified-stream keys coexist.

## Required Validation

Run before merging:

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
source .venv/bin/activate
pytest -q
mypy -p hypercore_sdk
```

## Release/Handoff Checklist

1. Verify CLI entrypoint resolves to local venv:
   - `which hypercore-sdk`
2. Verify imports:
   - `python -c "import hypercore_sdk; print(hypercore_sdk.__file__)"`
3. Run benchmark smoke:
   - `python3 examples/feed_latency_examples.py --runs 1 --coin BTC --skip-unified --skip-grpc`
4. Update:
   - `CHANGELOG.md`
   - `PROJECT_STATE.md`
5. For gRPC example/auth diagnostics changes:
   - verify the active endpoint behavior when credentials are available
   - note whether denial is local config drift or endpoint-side auth policy
