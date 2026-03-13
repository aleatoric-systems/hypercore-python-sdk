from __future__ import annotations

from hypercore_sdk.config import SDKConfig
from hypercore_sdk.status import StatusClient


class _FakeResponse:
    def __init__(self, body) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[_FakeResponse] = []

    def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": headers})
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def test_status_client_uses_expected_endpoints_and_auth() -> None:
    fake = _FakeClient()
    fake.responses = [
        _FakeResponse({"status": "ok"}),
        _FakeResponse({"snapshot": {"service": {"name": "status"}}}),
        _FakeResponse({"snapshot": {"service": {"name": "private"}}}),
        _FakeResponse({"tokens": []}),
    ]
    cfg = SDKConfig(status_url="https://status.example", status_token="secret")
    with StatusClient(cfg, http_client=fake) as client:
        assert client.health()["status"] == "ok"
        assert client.public_status()["snapshot"]["service"]["name"] == "status"
        assert client.private_status()["snapshot"]["service"]["name"] == "private"
        assert client.admin_tokens()["tokens"] == []

    assert fake.calls[0]["url"] == "https://status.example/healthz"
    assert fake.calls[1]["url"] == "https://status.example/api/v1/public/status"
    assert fake.calls[2]["headers"] == {"accept": "application/json", "authorization": "Bearer secret"}


def test_status_client_rejects_non_object_payload() -> None:
    fake = _FakeClient()
    fake.responses = [_FakeResponse([])]
    client = StatusClient(SDKConfig(status_url="https://status.example"), http_client=fake)
    try:
        try:
            client.public_status()
        except RuntimeError as exc:
            assert "Unexpected public status payload" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        client.close()


def test_status_client_closes_owned_client() -> None:
    client = StatusClient(SDKConfig(status_url="https://status.example"))
    client.close()
