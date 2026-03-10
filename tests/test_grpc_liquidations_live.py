from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "grpc_liquidations_live.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("examples.grpc_liquidations_live", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_parser_prefers_rpc_gateway_key_over_grpc_stream_key(monkeypatch) -> None:
    monkeypatch.delenv("ALEATORIC_GRPC_KEY", raising=False)
    monkeypatch.delenv("RPC_KEY", raising=False)
    monkeypatch.setenv("RPC_GATEWAY_KEY", "rpc_key")
    monkeypatch.setenv("HYPER_API_KEY", "hyper_key")
    monkeypatch.setenv("GRPC_STREAM_KEY", "grpc_key")
    monkeypatch.setenv("UNIFIED_STREAM_KEY", "unified_key")
    monkeypatch.setenv("UNIFIED_KEY", "unified_key")

    module = _load_module()
    args = module.build_parser().parse_args([])

    assert args.api_key == "rpc_key"
