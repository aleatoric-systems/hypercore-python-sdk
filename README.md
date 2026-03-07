# Hypercore Python SDK

Python SDK and CLI for:
- JSON-RPC access
- WebSocket market data
- gRPC bridge access
- Signed Hyperliquid trading actions

## Install

```bash
cd /Users/jaws/research/dev/aleatoric/public/hypercore-python-sdk
PIP_REQUIRE_VIRTUALENV=false python3 -m pip install -e .
```

## Trading Actions

List all available methods from Hyperliquid `Exchange` and `Info`:

```bash
hypercore-sdk trade actions --interface all
```

Generic method invocation:

```bash
hypercore-sdk trade call \
  --interface exchange \
  --method update_leverage \
  --kwargs-json '{"leverage":5,"name":"BTC","is_cross":true}' \
  --private-key "$HYPER_PRIVATE_KEY"
```

Convenience order/cancel:

```bash
hypercore-sdk trade order \
  --coin BTC \
  --side buy \
  --size 0.01 \
  --limit-px 120000 \
  --order-type-json '{"limit":{"tif":"Gtc"}}' \
  --private-key "$HYPER_PRIVATE_KEY"

hypercore-sdk trade cancel \
  --coin BTC \
  --oid 123456789 \
  --private-key "$HYPER_PRIVATE_KEY"
```
