from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_defines_runtime_and_dev_targets() -> None:
    dockerfile = _read("Dockerfile")

    assert "FROM python:3.11-slim AS base" in dockerfile
    assert "FROM base AS runtime" in dockerfile
    assert 'ENTRYPOINT ["hypercore-sdk"]' in dockerfile
    assert "FROM base AS dev" in dockerfile
    assert 'python -m pip install ".[dev]"' in dockerfile


def test_compose_exposes_expected_services() -> None:
    compose = _read("docker-compose.yml")

    for service in ("cli:", "ws-console:", "grpc-console:", "benchmark:", "validate:", "package:"):
        assert service in compose

    assert 'entrypoint: ["python", "examples/feed_latency_examples.py", "--out-json", "/output/hypercore_feed_compare.json"]' in compose
    assert "./artifacts:/output" in compose
    assert "./dist:/dist" in compose


def test_dockerignore_excludes_local_secrets_and_outputs() -> None:
    dockerignore = _read(".dockerignore")

    for entry in (".env", "api/.env", ".venv", "dist", "build", "hypercore_feed_compare.json"):
        assert entry in dockerignore
