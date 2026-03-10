from __future__ import annotations

from pathlib import Path

from hypercore_sdk.example_auth import (
    apply_env_aliases,
    clean_key,
    disk_ws_key_candidates,
    grpc_key_candidates,
    load_env_credentials,
    market_ws_key_candidates,
    mask_key,
    pick_key,
    rpc_key_candidates,
    split_key_list,
    unified_key_candidates,
)


def test_load_env_credentials_applies_aliases_and_deduplicates(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=api_key\nRPC_KEY=rpc_key\nUNIFIED_KEY=unified_key\n", encoding="utf-8")

    env: dict[str, str] = {}
    loaded = load_env_credentials(tmp_path, cwd=tmp_path, env=env)

    assert loaded == [str(env_file)]
    assert env["HYPER_API_KEY"] == "api_key"
    assert env["RPC_GATEWAY_KEY"] == "rpc_key"
    assert env["UNIFIED_STREAM_KEY"] == "unified_key"
    assert env["DISK_STREAM_KEY"] == "unified_key"
    assert env["GRPC_STREAM_KEY"] == "rpc_key"


def test_grpc_key_candidates_prefer_rpc_gateway_key(monkeypatch) -> None:
    monkeypatch.setenv("RPC_GATEWAY_KEY", "rpc_key")
    monkeypatch.setenv("GRPC_STREAM_KEY", "grpc_key")
    monkeypatch.setenv("UNIFIED_STREAM_KEY", "unified_key")
    monkeypatch.delenv("ALEATORIC_GRPC_KEY", raising=False)
    monkeypatch.delenv("RPC_KEY", raising=False)
    monkeypatch.delenv("HYPER_API_KEY", raising=False)
    monkeypatch.delenv("api_keys", raising=False)

    resolution = pick_key(None, grpc_key_candidates())

    assert resolution.value == "rpc_key"
    assert resolution.source == "RPC_GATEWAY_KEY"


def test_rpc_key_candidates_ignore_placeholder_values(monkeypatch) -> None:
    monkeypatch.setenv("RPC_GATEWAY_KEY", "${RPC_GATEWAY_KEY}")
    monkeypatch.setenv("RPC_KEY", " rpc_key ")
    monkeypatch.delenv("HYPER_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("api_keys", raising=False)

    resolution = pick_key(None, rpc_key_candidates())

    assert resolution.value == "rpc_key"
    assert resolution.source == "RPC_KEY"


def test_apply_env_aliases_uses_generic_or_unified_fallbacks() -> None:
    env = {"API_KEY": "api_key"}
    apply_env_aliases(env)
    assert env["HYPER_API_KEY"] == "api_key"
    assert env["GRPC_STREAM_KEY"] == "api_key"

    env = {"UNIFIED_STREAM_KEY": "unified_key"}
    apply_env_aliases(env)
    assert env["GRPC_STREAM_KEY"] == "unified_key"


def test_clean_mask_split_and_pick_key_helpers() -> None:
    assert clean_key(None) is None
    assert clean_key("  'quoted'  ") == "quoted"
    assert clean_key("${RPC_GATEWAY_KEY}") is None
    assert clean_key("bad key") is None
    assert clean_key("<secret>") is None
    assert mask_key("abcd1234") == "********"
    assert split_key_list("a, b\nc") == ["a", "b", "c"]

    resolution = pick_key(" explicit ", [])
    assert resolution.value == "explicit"
    assert resolution.source == "cli"

    resolution = pick_key(None, [])
    assert resolution.value is None
    assert resolution.source is None


def test_candidate_helpers_include_expected_sources(monkeypatch) -> None:
    monkeypatch.setenv("ALEATORIC_MARKET_WS_KEY", "ws_key")
    monkeypatch.setenv("UNIFIED_STREAM_KEY", "unified_key")
    monkeypatch.setenv("DISK_STREAM_KEY", "disk_key")
    monkeypatch.setenv("api_keys", "list_key")

    market_candidates = market_ws_key_candidates()
    unified_candidates = unified_key_candidates()
    disk_candidates = disk_ws_key_candidates()

    assert market_candidates[0] == ("ALEATORIC_MARKET_WS_KEY", "ws_key")
    assert unified_candidates[0] == ("UNIFIED_STREAM_KEY", "unified_key")
    assert disk_candidates[0] == ("DISK_STREAM_KEY", "disk_key")
    assert market_candidates[-1] == ("api_keys[0]", "list_key")
