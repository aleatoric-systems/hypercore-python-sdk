from __future__ import annotations

from hypercore_sdk.config import SDKConfig, _env_bool


def test_env_bool_defaults_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_FLAG", raising=False)
    assert _env_bool("FEATURE_FLAG", default=True) is True
    assert _env_bool("FEATURE_FLAG", default=False) is False


def test_env_bool_true_values(monkeypatch) -> None:
    for value in ["1", "true", "yes", "on", "TRUE"]:
        monkeypatch.setenv("FEATURE_FLAG", value)
        assert _env_bool("FEATURE_FLAG", default=False) is True


def test_auth_headers_with_api_key() -> None:
    cfg = SDKConfig(api_key="key-123")
    assert cfg.auth_headers() == {
        "content-type": "application/json",
        "x-api-key": "key-123",
    }


def test_auth_headers_without_api_key() -> None:
    cfg = SDKConfig(api_key=None)
    assert cfg.auth_headers() == {"content-type": "application/json"}
